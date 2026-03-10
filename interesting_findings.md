# Interesting Findings

## LLM Prioritization vs Statistical Association

During testing of the SNP triage pipeline for **coronary artery disease (CAD)** genes, an interesting observation emerged.

The statistical association ranking placed **LPA** below several well-known lipid genes, including **APOE**, **LDLR**, and **PCSK9**. However, the LLM-based reasoning module elevated **LPA** to **High Priority**.

### Comparison

| Gene | Association Score | LLM Priority |
|-----|-----|-----|
| APOE | 0.82 | High |
| LDLR | 0.74 | Medium |
| PCSK9 | 0.73 | High |
| LPA | 0.59 | High |

### Possible Explanations

Several factors may explain why the reasoning layer elevated **LPA**:

- The model likely incorporates **biological priors present in the training corpus**, including literature discussing cardiovascular genetics.
- **LPA is a well-established risk gene for coronary artery disease**, particularly through its effect on **lipoprotein(a) levels**.
- Regulatory variants affecting **LPA expression** can substantially influence circulating Lp(a) levels and cardiovascular risk.

### Interpretation

This observation highlights a potential benefit of combining:

- **statistical association signals**
- **variant functional annotation**
- **LLM-based mechanistic reasoning**

Rather than relying solely on raw association scores, the reasoning layer can incorporate biological plausibility and literature-informed context when prioritizing variants or genes.

### Implication for Variant Triage

This architecture suggests that **LLM-assisted reasoning layers may complement traditional GWAS-based ranking**, helping surface biologically meaningful candidates that might otherwise appear lower in purely statistical rankings.

---

## Notes

This observation was generated during exploratory testing of the **SNP Agentic Miner pipeline** and should be interpreted as a qualitative system behavior rather than a formal benchmark or validation result.