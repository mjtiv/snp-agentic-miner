#!/usr/bin/env python3.10

import os
import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

import os
from dotenv import load_dotenv
from openai import OpenAI


###############################################################
# SNP Agentic Miner (SAM)
#
# Overview
# --------
# SNP Agentic Miner is a Python pipeline designed to analyze a
# set of genetic variants (SNPs) in the context of a disease of
# interest. The program combines structured biomedical APIs
# with AI-assisted reasoning to identify biologically relevant
# variants and explain their potential role in disease.
#
# The pipeline follows a deterministic-first architecture:
#
# 1. A disease of interest is normalized using the Open Targets
#    platform to obtain a canonical disease identifier and
#    known synonyms.
#
# 2. SNPs are annotated using variant annotation APIs
#    (e.g., VEP or other services) to identify affected genes
#    and predicted functional consequences.
#
# 3. Gene-disease relationships are evaluated using evidence
#    from biomedical databases.
#
# 4. Genes are annotated with function
#
# 5. Merge All Tables
#
# 6. AI reasoning is applied to synthesize the structured data,
#    interpret variant relevance, and generate human-readable
#    explanations of possible disease mechanisms (limit to top 
#    25-50 hits).
#
# This approach separates deterministic data retrieval from
# AI interpretation, improving transparency and reducing
# hallucination risk while enabling flexible biological
# reasoning.
###############################################################


#########################################################################################################################
################################# Mining OpenTargets Term ID for Disease ################################################
#########################################################################################################################
###############################################################
# Open Targets Disease Normalization
#
# Purpose:
# Resolve the user-specified disease name into a canonical
# disease identifier (EFO ID) and collect known synonyms.
#
# Why this step exists:
# Biomedical databases and literature refer to diseases using
# many different names (e.g. "coronary artery disease",
# "coronary heart disease", "CAD", "coronary atherosclerosis").
#
# The Open Targets API provides:
#   - A canonical ontology identifier (EFO ID)
#   - Standard disease label
#   - Known synonyms used across biomedical resources
#
# This information is used later to:
#   1. Normalize disease references across databases
#   2. Improve gene–disease association queries
#   3. Expand literature searches
#   4. Provide context to the LLM reasoning stage
#
# Pipeline stage:
#
# Disease Name (user input)
#        ↓
# Open Targets API      
#        ↓
# Canonical Disease ID + Synonyms
#        ↓
# Variant Annotation + Gene Mapping
#        ↓
# Disease Relevance Scoring
#        ↓
# AI Interpretation
###############################################################


import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests

OT_GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"  # :contentReference[oaicite:2]{index=2}


@dataclass(frozen=True)
class DiseaseResolution:
    query: str
    efo_id: str
    name: str
    description: Optional[str]
    synonyms_by_relation: Dict[str, List[str]]
    db_xrefs: List[str]


class OpenTargetsClient:
    def __init__(self, graphql_url: str = OT_GRAPHQL_URL, timeout_s: int = 30):
        self.graphql_url = graphql_url
        self.timeout_s = timeout_s

    def _post(self, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        resp = requests.post(
            self.graphql_url,
            json={"query": query, "variables": variables},
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        payload = resp.json()
        if "errors" in payload and payload["errors"]:
            # Bubble up the first GraphQL error message (usually enough to debug).
            raise RuntimeError(payload["errors"][0].get("message", "OpenTargets GraphQL error"))
        return payload["data"]

    def map_disease_term(self, term: str) -> List[Dict[str, str]]:
        """
        Returns ranked hits for the disease term mapping.
        Each hit contains id + name + entity.
        """
        q = """
        query MapDisease($term: String!) {
          mapIds(queryTerms: [$term], entityNames: ["disease"]) {
            mappings {
              term
              hits {
                id
                name
                entity
              }
            }
          }
        }
        """
        data = self._post(q, {"term": term})
        mappings = data["mapIds"]["mappings"]
        if not mappings:
            return []
        hits = mappings[0].get("hits", []) or []
        # Keep disease hits only (defensive)
        return [h for h in hits if (h.get("entity") or "").lower() == "disease"]

    def fetch_disease_details(self, efo_id: str) -> Dict[str, Any]:
        q = """
        query DiseaseDetails($efoId: String!) {
          disease(efoId: $efoId) {
            id
            name
            description
            dbXRefs
            synonyms {
              relation
              terms
            }
          }
        }
        """
        data = self._post(q, {"efoId": efo_id})
        if not data.get("disease"):
            raise ValueError(f"No disease returned for efoId={efo_id}")
        return data["disease"]

    def resolve_disease(self, term: str) -> DiseaseResolution:
        hits = self.map_disease_term(term)
        if not hits:
            raise ValueError(f"No disease match found in Open Targets for: {term!r}")

        # Top hit is usually good enough for v1. You can later add disambiguation.
        top = hits[0]
        efo_id = top["id"]

        d = self.fetch_disease_details(efo_id)

        synonyms_by_relation: Dict[str, List[str]] = {}
        for syn in (d.get("synonyms") or []):
            rel = syn.get("relation") or "unknown"
            terms = syn.get("terms") or []
            # Normalize + dedupe while keeping order
            seen = set()
            cleaned = []
            for t in terms:
                t2 = (t or "").strip()
                if t2 and t2.lower() not in seen:
                    cleaned.append(t2)
                    seen.add(t2.lower())
            if cleaned:
                synonyms_by_relation[rel] = cleaned

        return DiseaseResolution(
            query=term,
            efo_id=d["id"],
            name=d["name"],
            description=d.get("description"),
            synonyms_by_relation=synonyms_by_relation,
            db_xrefs=d.get("dbXRefs") or [],
        )


def resolve_disease_with_cache(
    disease_of_interest: str,
    cache_path: str = "cache_disease_resolution.json",
) -> DiseaseResolution:
    """
    Resolve a disease name to a canonical Open Targets disease entry.

    This function queries the Open Targets GraphQL API to map a free-text
    disease description to a standardized disease ontology identifier
    (EFO ID). It also retrieves known synonyms and cross-references.

    Why this matters:
        Biomedical resources refer to the same disease using multiple
        terms. Normalizing the disease name allows downstream steps
        to consistently match gene-disease associations, pathways,
        and literature evidence.

    Inputs
    ------
    disease_name : str
        Free-text disease name provided by the user.

    Returns
    -------
    disease_info : dict
        {
            "disease_id": EFO identifier,
            "name": canonical disease name,
            "synonyms": list of alternative disease names,
            "description": ontology description
        }

    Used later for:
        - gene-disease association queries
        - literature search expansion
        - LLM context grounding
    """
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("query") == disease_of_interest and cached.get("efo_id"):
                return DiseaseResolution(
                    query=cached["query"],
                    efo_id=cached["efo_id"],
                    name=cached["name"],
                    description=cached.get("description"),
                    synonyms_by_relation=cached.get("synonyms_by_relation") or {},
                    db_xrefs=cached.get("db_xrefs") or [],
                )
        except Exception:
            # If cache is corrupt, just ignore and re-fetch.
            pass

    client = OpenTargetsClient()
    res = client.resolve_disease(disease_of_interest)

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "query": res.query,
                "efo_id": res.efo_id,
                "name": res.name,
                "description": res.description,
                "synonyms_by_relation": res.synonyms_by_relation,
                "db_xrefs": res.db_xrefs,
            },
            f,
            indent=2,
        )

    return res


#########################################################################################################################
###################################### Extract List of SNPs from File ###################################################
#########################################################################################################################


def get_list_of_snps(filename):

    """
    Opens the file to get list of the patents

    : Param filename: Name of the file being open
    : Return list_patents: List of the patents to be scraped
    
    """

    #print (filename)

    # Create empty list 
    list_of_snps = []

    #Open the file
    input_file = open(filename, "r")

    # Loop over lines
    for line in input_file:
        #print (line)
        line = line.rstrip("\n")

        # remove commas
        clean_id = line.replace(",", "")
        #print(clean_id)

        # Adds to the list
        list_of_snps.append(clean_id)

    input_file.close()
    
    return (list_of_snps)


#########################################################################################################################
################################################### Call VEP API ########################################################
#########################################################################################################################

###########################################################################
# SNP Agentic Miner (SAM)
# Configuration
###########################################################################

###########################################################################
# VEP Behavior Settings
###########################################################################
#
# These parameters control how the Ensembl Variant Effect Predictor (VEP)
# prioritizes transcript annotations returned from the API. Without these
# settings VEP returns consequences for *every transcript isoform* of nearby
# genes, which can create large and difficult-to-interpret outputs.
#
# The options below instruct VEP to prioritize biologically relevant
# transcripts and return concise annotations suitable for downstream
# analysis.
#
# pick
#   Selects a single "best" transcript consequence per variant using
#   Ensembl’s internal ranking system. This reduces transcript isoform explosion
#   and simplifies downstream interpretation.
#
# mane
#   Includes MANE Select annotations. MANE transcripts are jointly curated
#   by Ensembl and NCBI and represent a standardized transcript model for
#   each gene when available.
#
# canonical
#   Flags the Ensembl canonical transcript for the gene. Canonical
#   transcripts are often the most widely used reference isoforms.
#
# appris
#   Includes APPRIS annotation which identifies the principal protein
#   isoform based on structural, evolutionary, and functional evidence.
#
# variant_class
#   Adds a classification of the variant type (e.g., SNV, insertion,
#   deletion, substitution).
#
# hgvs
#   Provides HGVS nomenclature describing the variant at the transcript
#   and protein level (useful for human-readable reporting).
#
# Together these parameters produce a concise yet biologically meaningful
# annotation for each SNP while still allowing access to full transcript
# information if deeper inspection is required.
###########################################################################


# Website for VEP
ENSEMBL_REST = "https://rest.ensembl.org"

# Settings for VEP
SPECIES = "human"
ASSEMBLY = "GRCh38"

# VEP behavior settings
VEP_PARAMS = {
    "pick": 1,
    "mane": 1,
    "canonical": 1,
    "appris": 1,
    "variant_class": 1,
    "hgvs": 1
}


def ensembl_get(path: str, params=None, timeout_s: int = 30):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    url = f"{ENSEMBL_REST}{path}"
    r = requests.get(url, headers=headers, params=params or {}, timeout=timeout_s)
    r.raise_for_status()
    return r.json()


def rsid_to_mappings(rsid: str, species: str = SPECIES):
    """
    Returns Ensembl variation record for an rsID, including genomic mappings.
    """
    # Example endpoint: /variation/human/rs429358
    return ensembl_get(f"/variation/{species}/{rsid}")


def pick_primary_mapping(var_json: dict, assembly: str = ASSEMBLY):
    """
    Pick one mapping for v1. Prefer GRCh38, and a 'chromosome' seq_region_name.
    """
    mappings = var_json.get("mappings", []) or []
    for m in mappings:
        if (
            m.get("assembly_name") == assembly
            and (
                str(m.get("seq_region_name", "")).isdigit()
                or m.get("seq_region_name") in ["X", "Y", "MT"]
            )
        ):
            return m
    # fallback: first mapping
    return mappings[0] if mappings else None


def vep_region_consequences(
    chrom: str,
    start: int,
    end: int,
    allele: str,
    species: str = SPECIES,
):
    """
    Call Ensembl VEP REST region endpoint for a single allele.
    """

    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    # Endpoint form: /vep/human/region/{region}/{allele}
    region = f"{chrom}:{start}-{end}"
    url = f"{ENSEMBL_REST}/vep/{species}/region/{region}/{allele}"

    r = requests.get(
        url,
        headers=headers,
        params=VEP_PARAMS,   # <-- THIS is the important change
        timeout=30
    )

    r.raise_for_status()
    return r.json()


def annotate_rsid_with_vep(rsid: str):
    var = rsid_to_mappings(rsid)
    m = pick_primary_mapping(var)
    if not m:
        return {"rsid": rsid, "error": "No mapping returned"}

    chrom = m["seq_region_name"]
    start = m["start"]
    end = m["end"]

    # Ensembl variation mapping usually includes 'allele_string' like "T/C"
    allele_string = m.get("allele_string", "")
    # For v1, pick the ALT allele heuristically (second allele). You can refine later.
    alt = allele_string.split("/")[-1] if "/" in allele_string else None
    if not alt:
        return {"rsid": rsid, "error": f"Could not parse allele_string: {allele_string}"}

    vep = vep_region_consequences(chrom, start, end, alt)
    return {
        "rsid": rsid,
        "mapping": m,
        "vep": vep,
    }


def write_full_annotations(annotations, output_file="vep_full_annotations.json"):
    """
    Write the full raw VEP annotations to disk for manual inspection.
    This preserves the complete API response for each SNP.
    """

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(annotations, f, indent=2)

    print(f"Full VEP annotations written to: {output_file}")


def write_vep_excel_table(json_file="vep_full_annotations.json",
                          output_file="vep_annotations_table.tsv"):

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    header = [
        "RSID",
        "Chromosome",
        "Position",
        "Gene",
        "Transcript",
        "Consequence",
        "Impact",
        "AminoAcids",
        "Codons",
        "Biotype",
        "Distance",
        "Allele",
        "VariantClass"
    ]

    with open(output_file, "w") as out:

        out.write("\t".join(header) + "\n")

        for entry in data:

            rsid = entry.get("rsid")

            mapping = entry.get("mapping", {})
            chrom = mapping.get("seq_region_name")
            pos = mapping.get("start")
            allele = mapping.get("allele_string")

            vep = entry.get("vep", [])
            if not vep:
                continue

            v = vep[0]
            variant_class = v.get("variant_class")

            for tc in v.get("transcript_consequences", []):

                row = [
                    rsid,
                    str(chrom),
                    str(pos),
                    tc.get("gene_symbol"),
                    tc.get("transcript_id"),
                    ",".join(tc.get("consequence_terms", [])),
                    tc.get("impact"),
                    tc.get("amino_acids"),
                    tc.get("codons"),
                    tc.get("biotype"),
                    str(tc.get("distance")),
                    allele,
                    variant_class
                ]

                row = ["" if r is None else str(r) for r in row]

                out.write("\t".join(row) + "\n")

    print(f"Table written to {output_file}")


#########################################################################################################################
#################################### Examining Genes of Interest Disease Relationship ###################################
#########################################################################################################################

###############################################################
# Examining Genes of Interest
#
# Purpose:
# Identify which genes affected by the annotated SNPs are
# biologically relevant to the disease of interest.
#
# Pipeline steps:
#
# 1. Extract unique gene symbols from the SNP annotation table.
#    Multiple SNPs may map to the same gene, so duplicates are
#    removed.
#
# 2. Resolve each gene symbol to an Open Targets target ID.
#    Open Targets uses Ensembl gene identifiers internally,
#    so the gene symbol must first be mapped to the platform's
#    canonical target ID.
#
# 3. Query Open Targets for gene–disease association evidence.
#    Each gene is evaluated against the disease EFO ID and
#    assigned a relevance score (0–1) based on aggregated
#    evidence from genetics, literature, drugs, and other
#    biomedical datasets.
#
# Output:
# A table linking each gene to the disease relevance score,
# which will later be merged with the SNP annotation table
# for interpretation and ranking of candidate variants.
###############################################################

import csv

def get_unique_genes_from_tsv(tsv_file="vep_annotations_table.tsv"):
    """
    Extract unique gene symbols from the SNP annotation table.

    The VEP annotation table may contain multiple rows for the
    same gene because:
        - multiple SNPs affect the same gene
        - multiple transcript consequences may be reported

    This function reads the TSV file produced by the VEP step,
    collects the gene symbols, removes duplicates, and returns
    a list of unique genes for downstream disease relevance
    analysis.
    """
    genes = []
    seen = set()

    with open(tsv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")

        for row in reader:
            gene = (row.get("Gene") or "").strip()
            if not gene:
                continue
            if gene not in seen:
                seen.add(gene)
                genes.append(gene)

    return genes


# Open Targets GraphQL API endpoint
#
# This URL is the primary API interface for the Open Targets Platform.
# It allows the program to query biomedical data including:
#   - disease ontology identifiers (EFO IDs)
#   - gene–disease associations
#   - gene metadata and target identifiers
#
# The API uses GraphQL, which means queries specify exactly what
# fields of information should be returned rather than downloading
# entire database records.
#
# Documentation:
# https://platform.opentargets.org/api
#
OT_GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"


def ot_post(query: str, variables: dict) -> dict:
    """
    Helper function for sending GraphQL queries to the Open Targets API.
    This function posts a query and variables to the Open Targets server,
    checks for HTTP or GraphQL errors, and returns the data portion of the
    response as a Python dictionary.
    """
    resp = requests.post(
        OT_GRAPHQL_URL,
        json={"query": query, "variables": variables},
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errors"):
        raise RuntimeError(payload["errors"][0]["message"])
    return payload["data"]


def resolve_gene_to_target_id(gene_symbol: str):
    """
    Resolve a gene symbol to the corresponding Open Targets target ID.

    Open Targets internally indexes genes using Ensembl gene
    identifiers (e.g. ENSG00000130203 for APOE). Because the SNP
    annotation step provides gene symbols, this function queries
    the Open Targets search API to map the symbol to the platform's
    canonical target ID.

    Example:
        APOE → ENSG00000130203

    The returned target ID is required for downstream gene–disease
    association queries.
    """
    query = """
    query ResolveGene($query: String!) {
      search(queryString: $query, entityNames: ["target"]) {
        hits {
          id
          entity
          name
          description
        }
      }
    }
    """
    data = ot_post(query, {"query": gene_symbol})
    hits = data["search"]["hits"]
    hits = [h for h in hits if h.get("entity") == "target"]

    if not hits:
        return None

    return {
        "gene_symbol": gene_symbol,
        "target_id": hits[0]["id"],
        "target_name": hits[0]["name"],
        "description": hits[0].get("description"),
    }


def evaluate_gene_disease(target_id: str, disease_efo_id: str, gene_symbol: str):
    """
    Evaluate the association between a gene and the disease of interest.

    This function queries the Open Targets platform for genes known
    to be associated with the specified disease. Each associated gene
    is assigned an evidence score ranging from 0 to 1.

    The function checks whether the target gene appears among the
    disease-associated targets and returns the corresponding score.

    Possible outcomes:

        1. Disease not found
           The requested disease ID is not returned by the API.

        2. Gene found in disease-associated targets
           A non-zero association score is returned.

        3. Gene not associated with the disease
           The gene is not listed among associated targets and
           a score of 0.0 is assigned.

    This scoring step allows the pipeline to prioritize genes
    that are biologically relevant to the disease.
    """
    query = """
    query DiseaseAssociatedTargets($diseaseId: String!) {
      disease(efoId: $diseaseId) {
        id
        name
        associatedTargets(page: { index: 0, size: 500 }) {
          count
          rows {
            score
            target {
              id
              approvedSymbol
            }
          }
        }
      }
    }
    """
    data = ot_post(query, {"diseaseId": disease_efo_id})

    # Disease NOT Found
    disease = data.get("disease")
    if not disease:
        return {
            "target_id": target_id,
            "disease_id": disease_efo_id,
            "association_score": None,
            "error": "Disease not found"
        }

    # Target Found for the Disease
    rows = disease.get("associatedTargets", {}).get("rows", [])
    for row in rows:
        target = row.get("target", {})
        if target.get("id") == target_id:
            return {
                "target_id": target_id,
                "gene_symbol": target.get("approvedSymbol"),
                "disease_id": disease["id"],
                "disease_name": disease["name"],
                "association_score": row.get("score", 0.0),
            }

    # Final Return
    return {
        "target_id": target_id,
        "gene_symbol": gene_symbol,
        "disease_id": disease["id"],
        "disease_name": disease["name"],
        "association_score": 0.0,
    }


def write_gene_disease_scores(results, output_file="gene_disease_scores.tsv"):
    """
    Write gene–disease association scores to a TSV file.

    Each row links a gene symbol to:
        - the Open Targets target ID
        - the disease identifier
        - the disease name
        - the association score

    This table will later be merged with the SNP annotation
    table to identify which SNPs occur in genes strongly
    associated with the disease.
    """
    header = ["GeneSymbol", "TargetID", "DiseaseID", "DiseaseName", "AssociationScore"]

    with open(output_file, "w", encoding="utf-8") as out:
        out.write("\t".join(header) + "\n")
        for r in results:
            row = [
                r.get("gene_symbol", ""),
                r.get("target_id", ""),
                r.get("disease_id", ""),
                r.get("disease_name", ""),
                str(r.get("association_score", "")),
            ]
            out.write("\t".join(row) + "\n")

#########################################################################################################################
############################################### Examining Genes Functions ###############################################
#########################################################################################################################


def get_gene_function(target_id: str, gene_symbol: str):
    """
    Query Open Targets for basic gene / target annotation information.

    This function retrieves a short descriptive summary for a gene
    using the Open Targets target endpoint. The returned description
    can later be merged with SNP annotations and disease relevance
    scores to improve biological interpretation.
    """
    query = """
    query TargetAnnotation($targetId: String!) {
      target(ensemblId: $targetId) {
        id
        approvedSymbol
        approvedName
        functionDescriptions
      }
    }
    """
    data = ot_post(query, {"targetId": target_id})

    target = data.get("target")
    if not target:
        return {
            "gene_symbol": gene_symbol,
            "target_id": target_id,
            "target_name": None,
            "gene_function": None,
        }

    function_descriptions = target.get("functionDescriptions") or []

    # Join multiple descriptions into one string for TSV output
    gene_function = " | ".join(function_descriptions) if function_descriptions else ""

    return {
        "gene_symbol": gene_symbol,
        "target_id": target.get("id"),
        "target_name": target.get("approvedName"),
        "gene_function": gene_function,
    }


def write_gene_functions(results, output_file="gene_functions.tsv"):
    header = ["GeneSymbol", "TargetID", "TargetName", "GeneFunction"]

    with open(output_file, "w", encoding="utf-8") as out:
        out.write("\t".join(header) + "\n")
        for r in results:
            row = [
                r.get("gene_symbol", ""),
                r.get("target_id", ""),
                r.get("target_name", ""),
                r.get("gene_function", ""),
            ]
            out.write("\t".join(row) + "\n")


#########################################################################################################################
####################################### Genes Function Compression ######################################################
#########################################################################################################################

# -------------------------------------------------------------------
# OpenAI client
# Requires OPENAI_API_KEY in environment variables
# -------------------------------------------------------------------
load_dotenv()
client = OpenAI()

def reduce_gene_function(gene_symbol: str, raw_function: str) -> str:
    """
    Send a gene symbol and raw gene description to the OpenAI API and
    return a short, normalized function summary.

    Rules for the model:
      - max 15 words
      - plain English
      - one sentence fragment
      - no disease interpretation
      - no speculation
    """

    if not raw_function or not raw_function.strip():
        return ""

    prompt = f"""
You are compressing gene function descriptions for a genomics pipeline.

Task:
Given a gene symbol and a raw gene function description, produce a short,
plain-English summary of the gene's main biological role.

Rules:
- Maximum 15 words
- One sentence fragment only
- No disease interpretation
- No speculation
- Keep only the most important biological function
- Return valid JSON only
- Use this JSON format:
  {{"short_function": "..."}}

Gene: {gene_symbol}
Description: {raw_function}
""".strip()

    response = client.responses.create(
        model="gpt-5-mini",
        input=prompt,
    )

    text = response.output_text.strip()

    try:
        payload = json.loads(text)
        return payload.get("short_function", "").strip()
    except json.JSONDecodeError:
        # fallback: if model returns plain text instead of JSON
        return text[:120].strip()


def read_gene_functions_tsv(tsv_file: str = "gene_functions.tsv") -> List[Dict[str, str]]:
    """
    Read gene_functions.tsv into a list of dictionaries.
    """
    rows = []
    with open(tsv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(row)
    return rows


def write_reduced_gene_functions(
    rows: List[Dict[str, str]],
    output_file: str = "gene_functions_reduced.tsv"
) -> None:
    """
    Write the reduced gene function table to disk.
    """
    header = ["GeneSymbol", "TargetID", "TargetName", "RawFunction", "ShortFunction"]

    with open(output_file, "w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out, delimiter="\t")
        writer.writerow(header)

        for row in rows:
            writer.writerow([
                row.get("GeneSymbol", ""),
                row.get("TargetID", ""),
                row.get("TargetName", ""),
                row.get("GeneFunction", ""),
                row.get("ShortFunction", ""),
            ])

    print(f"Reduced gene function table written to: {output_file}")


#########################################################################################################################
########################################### Merge the Files and Reduce  #################################################
#########################################################################################################################

def merge_master_table(
    vep_file: str = "vep_annotations_table.tsv",
    disease_file: str = "gene_disease_scores.tsv",
    function_file: str = "gene_functions_reduced.tsv",
    output_file: str = "master_snp_gene_annotations.tsv",
) -> None:
    """
    Merge:
      1. VEP SNP annotations
      2. Gene-disease association scores
      3. Reduced gene function annotations

    Join key:
      VEP.Gene  <->  GeneSymbol in the other two files

    Output:
      A master TSV where each SNP/transcript row is enriched with:
        - disease association score
        - target ID
        - target name
        - short gene function summary
    """

    # -----------------------------
    # Read gene_disease_scores.tsv
    # -----------------------------
    disease_lookup = {}
    with open(disease_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            gene_symbol = (row.get("GeneSymbol") or "").strip()
            if gene_symbol:
                disease_lookup[gene_symbol] = row

    # -------------------------------------
    # Read gene_functions_reduced.tsv
    # -------------------------------------
    function_lookup = {}
    with open(function_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            gene_symbol = (row.get("GeneSymbol") or "").strip()
            if gene_symbol:
                function_lookup[gene_symbol] = row

    # -----------------------------
    # Read VEP table + merge fields
    # -----------------------------
    merged_rows = []

    with open(vep_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")

        for row in reader:
            gene_symbol = (row.get("Gene") or "").strip()

            disease_row = disease_lookup.get(gene_symbol, {})
            function_row = function_lookup.get(gene_symbol, {})

            merged_row = {
                # Original VEP columns
                "RSID": row.get("RSID", ""),
                "Chromosome": row.get("Chromosome", ""),
                "Position": row.get("Position", ""),
                "Gene": row.get("Gene", ""),
                "Transcript": row.get("Transcript", ""),
                "Consequence": row.get("Consequence", ""),
                "Impact": row.get("Impact", ""),
                "AminoAcids": row.get("AminoAcids", ""),
                "Codons": row.get("Codons", ""),
                "Biotype": row.get("Biotype", ""),
                "Distance": row.get("Distance", ""),
                "Allele": row.get("Allele", ""),
                "VariantClass": row.get("VariantClass", ""),

                # Gene-disease fields
                "TargetID": disease_row.get("TargetID", function_row.get("TargetID", "")),
                "DiseaseID": disease_row.get("DiseaseID", ""),
                "DiseaseName": disease_row.get("DiseaseName", ""),
                "AssociationScore": disease_row.get("AssociationScore", ""),

                # Gene function fields
                "TargetName": function_row.get("TargetName", ""),
                "RawFunction": function_row.get("RawFunction", ""),
                "ShortFunction": function_row.get("ShortFunction", ""),
            }

            merged_rows.append(merged_row)

    # -----------------------------
    # Write merged master TSV
    # -----------------------------
    header = [
        "RSID",
        "Chromosome",
        "Position",
        "Gene",
        "Transcript",
        "Consequence",
        "Impact",
        "AminoAcids",
        "Codons",
        "Biotype",
        "Distance",
        "Allele",
        "VariantClass",
        "TargetID",
        "DiseaseID",
        "DiseaseName",
        "AssociationScore",
        "TargetName",
        "RawFunction",
        "ShortFunction",
    ]

    with open(output_file, "w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=header, delimiter="\t")
        writer.writeheader()
        writer.writerows(merged_rows)

    print(f"Master merged table written to: {output_file}")
    print(f"Total merged rows: {len(merged_rows)}")


def reduce_master_for_llm(
    input_file="master_snp_gene_annotations.tsv",
    output_file="master_snp_gene_annotations_llm.tsv",
):
    """
    Reduce the large master SNP annotation table to only the fields
    needed for later LLM interpretation.

    This keeps token size small and removes unnecessary columns.
    """

    keep_columns = [
        "Gene",
        "RSID",
        "Consequence",
        "Impact",
        "VariantClass",
        "AssociationScore",
        "DiseaseName",
        "ShortFunction",
    ]

    reduced_rows = []

    with open(input_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")

        for row in reader:
            reduced_row = {}

            for col in keep_columns:
                reduced_row[col] = (row.get(col) or "").strip()

            reduced_rows.append(reduced_row)

    with open(output_file, "w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=keep_columns, delimiter="\t")
        writer.writeheader()
        writer.writerows(reduced_rows)

    print(f"Reduced LLM table written to: {output_file}")
    print(f"Rows written: {len(reduced_rows)}")


#########################################################################################################################
########################################## Analyze List of Genes using LLM  #############################################
#########################################################################################################################


def analyze_variant_row(row):

    prompt = f"""
You are analyzing a genetic variant.

Return JSON only.

Variant data:
Gene: {row['Gene']}
RSID: {row['RSID']}
Consequence: {row['Consequence']}
Impact: {row['Impact']}
VariantClass: {row['VariantClass']}
AssociationScore: {row['AssociationScore']}
Disease: {row['DiseaseName']}
GeneFunction: {row['ShortFunction']}

Tasks:
1. Evaluate biological plausibility for disease relevance.
2. Assign mechanism category.
3. Assign priority.

Rules:
- Do NOT invent pathways or networks.
- Evaluate only this gene/variant.
- Use conservative reasoning.

Return JSON:

{{
"Plausibility": "",
"MechanismCategory": "",
"Priority": "",
"Rationale": ""
}}
"""

    response = client.responses.create(
        model="gpt-5-mini",
        input=prompt
    )

    text = response.output_text.strip()

    try:
        return json.loads(text)
    except:
        return {
            "Plausibility": "",
            "MechanismCategory": "",
            "Priority": "",
            "Rationale": text
        }


def run_llm_variant_analysis(
    input_file="master_snp_gene_annotations_llm.tsv",
    output_file="variant_llm_analysis.tsv",
):

    results = []

    with open(input_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")

        for row in reader:

            print(f"Analyzing {row['RSID']} ({row['Gene']})")

            analysis = analyze_variant_row(row)

            results.append({
                "Gene": row["Gene"],
                "RSID": row["RSID"],
                "Plausibility": analysis.get("Plausibility",""),
                "MechanismCategory": analysis.get("MechanismCategory",""),
                "Priority": analysis.get("Priority",""),
                "Rationale": analysis.get("Rationale","")
            })

    header = [
        "Gene",
        "RSID",
        "Plausibility",
        "MechanismCategory",
        "Priority",
        "Rationale"
    ]

    with open(output_file, "w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=header, delimiter="\t")
        writer.writeheader()
        writer.writerows(results)

    print(f"LLM variant analysis written to: {output_file}")



#########################################################################################################################
############################################ Main Function ##############################################################
#########################################################################################################################




def main():

    ################################Parameters#############################

    # Disease of Interest
    disease_of_interest = "Coronary Artery Disease"

    # File of SNPs of Interest
    file_of_snps = "list_of_snps.txt"

    #######################################################################
    
    print ("Starting Program")
    print ("\n")

    # Normalize disease name and gather synonyms using Open Targets
    # 0) Resolve disease name -> EFO ID + synonyms (Open Targets)
    disease = resolve_disease_with_cache(disease_of_interest)
    print(f"Disease resolved: {disease.query!r} -> {disease.efo_id} ({disease.name})")
    print("Synonyms (grouped):")
    for rel, terms in disease.synonyms_by_relation.items():
        print(f"  - {rel}: {terms[:10]}{' ...' if len(terms) > 10 else ''}")
    print ("\n")

    # Get the List of SNPs
    print ("Getting the list of SNPs")
    list_of_snps = get_list_of_snps(file_of_snps)
    print (list_of_snps)
    print ("\n")

    print ("Annotate the SNPs using VEP API")
    # WARNING- BIG ISSUE VEP ANNOTATES TONS!!!
    annotations = [annotate_rsid_with_vep(rs) for rs in list_of_snps]
    #print (annotations)
    print ("Done Annotating the SNPs")
    print ("\n")
    
    # Save raw annotations for manual review
    print ("Writing the Full Annotations to File")
    write_full_annotations(annotations)
    print ("Done Writing Annotations")
    print ("\n")

    # Convert Results to a Readable Excel Table
    print ("Writing TSV File of SNPs (Readable)")
    write_vep_excel_table()
    print ("Done Writing TSV")
    print ("\n")

    ### VARIABLES FOR TESTING ONLY ###
    #disease_efo_id = "EFO_0001645"
    #disease_name = "coronary artery disease"
    
    print ("Get the List of Genes from VEP Annotation")
    genes = get_unique_genes_from_tsv()
    print(genes)
    print ("\n")

    # Get the Disease EFO ID from Earlier
    disease_efo_id = disease.efo_id

    print("\nResolving genes and scoring disease associations")
    results = []

    # Loops over the list of genes identified from the SNPs
    for gene in genes:
        target = resolve_gene_to_target_id(gene)
        if not target:
            print(f"{gene} -> no target found")
            continue

        assoc = evaluate_gene_disease(target["target_id"], disease_efo_id, gene)
        results.append(assoc)
        print(f"{gene} -> {assoc['association_score']}")
    print ("\n")

    # Writes the disease scores to a file
    print ("Writing the Disease Scores to File")
    write_gene_disease_scores(results)
    print ("Done Writing Scores")
    print ("\n")


    print("\nResolving genes and collecting function annotations")
    gene_function_results = []
    for gene in genes:
        target = resolve_gene_to_target_id(gene)
        if not target:
            print(f"{gene} -> no target found")
            continue
        func = get_gene_function(target["target_id"], gene)
        gene_function_results.append(func)
        print(f"{gene} -> function retrieved")

    print ("Writing Gene Function Results")
    write_gene_functions(gene_function_results)
    print ("Done Writing Results")
    print ("\n")
    

    print("Reading gene_functions.tsv")
    rows = read_gene_functions_tsv("gene_functions.tsv")
    reduced_rows = []
    for row in rows:
        gene_symbol = (row.get("GeneSymbol") or "").strip()
        target_id = (row.get("TargetID") or "").strip()
        target_name = (row.get("TargetName") or "").strip()
        raw_function = (row.get("GeneFunction") or "").strip()

        print(f"Reducing function for {gene_symbol}")

        short_function = reduce_gene_function(gene_symbol, raw_function)

        reduced_rows.append({
            "GeneSymbol": gene_symbol,
            "TargetID": target_id,
            "TargetName": target_name,
            "GeneFunction": raw_function,
            "ShortFunction": short_function,
        })

    print ("Writing Reduced Functions to File")
    write_reduced_gene_functions(reduced_rows, "gene_functions_reduced.tsv")
    print ("Done Writing Reduced Functions to File")
    print ("\n")

    print ("Creating Master Table")
    merge_master_table(
        vep_file="vep_annotations_table.tsv",
        disease_file="gene_disease_scores.tsv",
        function_file="gene_functions_reduced.tsv",
        output_file="master_snp_gene_annotations.tsv",
    )
    print ("Done Creating Master Table")
    print ("\n")

    print("Reducing master table for LLM analysis")
    reduce_master_for_llm(
        input_file="master_snp_gene_annotations.tsv",
        output_file="master_snp_gene_annotations_llm.tsv",
    )
    print ("Done Reduction")
    print ("\n")

    print ("Running the LLM Analysis of Variants")
    run_llm_variant_analysis()
    print ("\n")
    print ("\n")

    print ("Done Running Program")

main()        












