SNP Agentic Miner (SAM)

Overview SNP Agentic Miner (SAM) is a Python pipeline that analyzes
genetic variants (SNPs) in the context of a disease of interest using a
combination of biomedical APIs and controlled LLM reasoning.

The system follows a deterministic-first architecture: biological data
is retrieved from structured databases, and LLMs are used only for
compression and interpretation, reducing hallucination risk while
enabling flexible biological reasoning.

The pipeline produces a structured variant interpretation report that
highlights biologically relevant variants and explains their potential
mechanisms.

------------------------------------------------------------------------

Architecture

User SNP List ↓ Variant Annotation (VEP) ↓ Gene Extraction ↓
Gene–Disease Association Scoring (Open Targets) ↓ Gene Function
Retrieval (Open Targets) ↓ LLM Gene Function Compression ↓ Master
Variant Annotation Table ↓ Reduced LLM Input Table ↓ LLM Variant
Interpretation ↓ Final Variant Analysis Report

This architecture ensures that biological evidence is grounded in
curated databases, while the LLM performs structured interpretation
rather than raw discovery.

------------------------------------------------------------------------

Pipeline Steps

1.  Disease Normalization The pipeline resolves a user-specified disease
    name using the Open Targets API to obtain a canonical disease
    identifier (EFO ID) and synonyms.

Example: Input: Coronary Artery Disease Output: EFO_0001645

2.  Variant Annotation Each SNP is annotated using the Ensembl Variant
    Effect Predictor (VEP), which returns genomic location, affected
    gene, transcript consequence, predicted functional impact, and
    variant classification.

Output file: vep_annotations_table.tsv

3.  Gene–Disease Association Scoring Genes affected by the SNPs are
    evaluated against the disease using Open Targets evidence scores
    that integrate multiple biomedical datasets.

Output file: gene_disease_scores.tsv

4.  Gene Function Retrieval The pipeline retrieves gene functional
    descriptions from Open Targets target annotations.

Output file: gene_functions.tsv

5.  Gene Function Compression (LLM) Gene function descriptions are
    compressed into short biological summaries using an LLM.

Example: Raw: “Proprotein convertase subtilisin/kexin type 9 regulates
degradation of LDL receptors…”

Compressed: “Regulates LDL receptor degradation controlling cholesterol
levels.”

Output file: gene_functions_reduced.tsv

6.  Master Annotation Table All deterministic evidence is merged into a
    single structured dataset.

Output file: master_snp_gene_annotations.tsv

7.  Reduced LLM Input Table To minimize token usage and keep the model
    focused, a reduced table is created containing only key
    interpretation fields.

Output file: master_snp_gene_annotations_llm.tsv

Fields include: Gene RSID Variant consequence Impact Variant class
Disease association score Gene function summary

8.  LLM Variant Interpretation Each SNP is evaluated individually by the
    LLM to produce structured interpretations.

The model assigns: - Plausibility - Mechanism Category - Priority -
Rationale

Example output:

Gene | RSID | Plausibility | Mechanism | Priority | Rationale APOE |
rs429358 | High | Altered protein function | High | Missense variant
affecting APOE lipid metabolism. PCSK9 | rs11591147 | High | Loss of
function | High | PCSK9 regulates LDL receptor turnover affecting
cholesterol levels.

Final output file: variant_llm_analysis.tsv

------------------------------------------------------------------------

Example Output Files

vep_annotations_table.tsv gene_disease_scores.tsv
gene_functions_reduced.tsv master_snp_gene_annotations.tsv
master_snp_gene_annotations_llm.tsv variant_llm_analysis.tsv

------------------------------------------------------------------------

Installation

Clone the repository:

git clone https://github.com/yourusername/snp-agentic-miner.git cd
snp-agentic-miner

Install dependencies:

pip install -r requirements.txt

Set environment variable:

OPENAI_API_KEY=your_key_here

------------------------------------------------------------------------

Running the Pipeline

Provide a file containing SNP identifiers:

list_of_snps.txt

Example:

rs429358 rs688 rs11591147

Run the program:

python SNP_Agentic_Miner.py

The pipeline will generate the annotation tables and final variant
interpretation report.

------------------------------------------------------------------------

Design Principles

Deterministic Evidence First Biological evidence is retrieved from
curated biomedical databases before AI interpretation.

Controlled LLM Usage LLMs are used for summarization and interpretation,
not raw discovery.

Transparent Intermediate Artifacts Each pipeline stage produces a
standalone file to improve debugging and reproducibility.

Variant-Level Interpretation Variants are evaluated individually to
avoid context contamination between SNPs.

------------------------------------------------------------------------

Limitations

This prototype identifies and interprets disease-relevant SNP loci but
does not yet incorporate genotype directionality (risk allele matching).

Future versions may include: - genotype parsing - risk allele matching -
population-specific risk interpretation - polygenic risk integration

------------------------------------------------------------------------

License MIT License

------------------------------------------------------------------------

Acknowledgments

This project integrates data from: - Ensembl Variant Effect Predictor
(VEP) - Open Targets Platform
