# SNP Agentic Miner (SAM)

SNP Agentic Miner (SAM) is a Python pipeline that analyzes genetic
variants (SNPs) in the context of a disease of interest using biomedical
APIs and controlled LLM reasoning.

The system follows a **deterministic‑first architecture**: biological
evidence is retrieved from structured databases, and LLMs are used only
for **compression and interpretation**, reducing hallucination risk
while enabling flexible biological reasoning.

The pipeline produces a **structured variant interpretation report**
highlighting biologically relevant variants and explaining their
potential mechanisms.

------------------------------------------------------------------------

# Architecture

SNP Agentic Miner (SAM) follows a **deterministic-first, agentic RAG pipeline** for variant interpretation.

![SNP Agentic Miner Pipeline Overview](Pipeline_Overview_Figure.png)

The pipeline moves through three major layers:

1. **Deterministic variant annotation**
   - User SNP list and disease input
   - Variant annotation with **VEP**
   - Gene mapping
   - Gene–disease association scoring with **Open Targets**

2. **Grounded biological context building**
   - Gene function retrieval from **Open Targets**
   - LLM-based gene function compression
   - Creation of a master variant annotation table
   - Reduction into a compact LLM-ready input table

3. **Controlled LLM interpretation**
   - Row-by-row LLM variant interpretation
   - Structured final variant analysis report

This architecture keeps **biological evidence grounded in curated databases** while the LLM performs **controlled compression and interpretation rather than raw discovery**.

------------------------------------------------------------------------

# Pipeline Steps

## 1. Disease Normalization

The pipeline resolves a user‑specified disease name using the **Open
Targets API** to obtain a canonical disease identifier (EFO ID) and
synonyms.

Example:

    Input: Coronary Artery Disease
    Output: EFO_0001645

------------------------------------------------------------------------

## 2. Variant Annotation

Each SNP is annotated using the **Ensembl Variant Effect Predictor
(VEP)**.

Returned annotations include:

-   genomic location
-   affected gene
-   transcript consequence
-   predicted functional impact
-   variant classification

Output file:

    vep_annotations_table.tsv

------------------------------------------------------------------------

## 3. Gene--Disease Association Scoring

Genes affected by SNPs are evaluated against the disease using **Open
Targets evidence scores**.

These scores integrate multiple data sources:

-   genetics studies
-   literature evidence
-   drug targets
-   pathway databases

Output file:

    gene_disease_scores.tsv

------------------------------------------------------------------------

## 4. Gene Function Retrieval

The pipeline retrieves gene functional descriptions from **Open Targets
target annotations**.

Output file:

    gene_functions.tsv

------------------------------------------------------------------------

## 5. Gene Function Compression (LLM)

Gene function descriptions are often long and redundant.

An LLM compresses these descriptions into concise biological summaries.

Example:

Raw:

    Proprotein convertase subtilisin/kexin type 9 regulates degradation of LDL receptors.

Compressed:

    Regulates LDL receptor degradation controlling cholesterol levels.

Output file:

    gene_functions_reduced.tsv

------------------------------------------------------------------------

## 6. Master Annotation Table

All deterministic evidence is merged into a single structured dataset.

Output file:

    master_snp_gene_annotations.tsv

Fields include:

-   SNP identifier
-   gene
-   variant consequence
-   disease association score
-   gene function summary

------------------------------------------------------------------------

## 7. Reduced LLM Input Table

To minimize token usage and maintain model focus, a reduced table is
created containing only key interpretation fields.

Output file:

    master_snp_gene_annotations_llm.tsv

Fields include:

-   Gene
-   RSID
-   Consequence
-   Impact
-   VariantClass
-   AssociationScore
-   DiseaseName
-   ShortFunction

------------------------------------------------------------------------

## 8. LLM Variant Interpretation

Each SNP is evaluated individually by an LLM to produce structured
interpretation fields:

-   **Plausibility**
-   **Mechanism Category**
-   **Priority**
-   **Rationale**

Example output:

  ----------------------------------------------------------------------------
  Gene        RSID         Plausibility   Mechanism   Priority    Rationale
  ----------- ------------ -------------- ----------- ----------- ------------
  APOE        rs429358     High           Altered     High        Missense
                                          protein                 variant
                                          function                affecting
                                                                  APOE lipid
                                                                  metabolism

  PCSK9       rs11591147   High           Loss of     High        PCSK9
                                          function                regulates
                                                                  LDL receptor
                                                                  turnover
  ----------------------------------------------------------------------------

Final output file:

    variant_llm_analysis.tsv

------------------------------------------------------------------------

# Example Output Files

    vep_annotations_table.tsv
    gene_disease_scores.tsv
    gene_functions_reduced.tsv
    master_snp_gene_annotations.tsv
    master_snp_gene_annotations_llm.tsv
    variant_llm_analysis.tsv

------------------------------------------------------------------------

# Installation

Clone the repository:

``` bash
git clone https://github.com/yourusername/snp-agentic-miner.git
cd snp-agentic-miner
```

Install dependencies:

``` bash
pip install -r requirements.txt
```

Set environment variable:

    OPENAI_API_KEY=your_key_here

------------------------------------------------------------------------

# Running the Pipeline

Provide a SNP list file:

    list_of_snps.txt

Example:

    rs429358
    rs688
    rs11591147

Run the program:

``` bash
python SNP_Agentic_Miner.py
```

The pipeline will generate the annotation tables and final variant
interpretation report.

------------------------------------------------------------------------

# Design Principles

### Deterministic Evidence First

Biological evidence is retrieved from curated databases before any AI
interpretation.

### Controlled LLM Usage

LLMs are used for summarization and structured interpretation --- not
raw discovery.

### Transparent Intermediate Artifacts

Each pipeline stage produces a standalone file for debugging and
reproducibility.

### Variant-Level Interpretation

Variants are evaluated individually to prevent context contamination.

------------------------------------------------------------------------

# Limitations

This prototype identifies and interprets disease‑relevant SNP loci but
**does not yet incorporate genotype directionality** (risk allele
matching).

Future improvements may include:

-   genotype parsing
-   risk allele matching
-   population‑specific interpretation
-   polygenic risk integration

------------------------------------------------------------------------

# License

MIT License

------------------------------------------------------------------------

# Acknowledgments

This project integrates data from:

-   **Ensembl Variant Effect Predictor (VEP)**
-   **Open Targets Platform**
