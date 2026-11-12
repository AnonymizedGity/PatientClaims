# Source pools

Fixed selections from the source datasets, made before the conversion. Each `<dataset>/manifest.json` records the
selection rule, the source release or checksum, the source row identifiers and the output checksums.

| Pool | Rows | Selection |
|---|---:|---|
| `ddxplus` | 3,875 | Adult test patients; exact duplicate symptom profiles collapsed; within each diagnosis, profiles more similar than Jaccard 0.75 (over symptom tokens, categorical values kept, antecedents and demographics left out) removed greedily and deterministically; at most 100 per diagnosis (10 diagnoses have fewer). The rows are included (`source_records/`), with the dataset's condition and evidence metadata (`source_metadata/`). |
| `medcasereasoning` | 493 | All test records that pass a screen for adult, patient-like, encounter-like cases with no missing media, no leaked diagnosis and usable reasoning. Only the manifest is included; the study's 100 cases were then chosen from it (`../medcasereasoning/selection/`). |
| `agentclinic_medqa_extended` | 165 | All adult records; 21 cases whose visible text contains a diagnosis alias were flagged for cleanup during conversion. Only the manifest is included; 150 were converted (`../agentclinic/selected_150.json`). |
