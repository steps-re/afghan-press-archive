# Overview
This dataset provides a full-text transcription of the Afghan Press Archive, focusing on lithographed Persian and Pashto periodicals from 1911 to 1918.

# Context
The original manuscript images are drawn from the Afghanistan Digital Library at New York University. We rely on the following rights statement from NYU regarding the images: "All works presented on this website are, unless otherwise indicated, in the public domain. The images available on this website may be freely reproduced, distributed and transmitted by anyone for any purpose, commercial or non-commercial."

# Method
The dataset was produced using machine-generated transcription. We established a baseline accuracy on existing sources: our pipeline achieved a Character Error Rate (CER) of 0.36 against a modern typeset edition of a 102-page chronicle. However, the edition itself has a known CER floor of 0.19 due to differences in spelling and modernization. On a very small sample of n=3 human-transcribed manuscript passages, the pipeline achieved a much lower CER of 0.068.

# Dataset description
The archive consists of 5,800 pages of lithographed Nastaliq text. Due to the lack of pre-existing transcriptions for this specific subset, a true page-level validation of the full corpus remains pending.

# Reuse potential
This dataset can serve as a foundation for historical and linguistic analysis of early 20th-century Afghanistan. 

# Blocker
Full validation and final dataset release are currently blocked by the need for 30 to 50 human-transcribed pages of the 1911 to 1918 lithographs to serve as a definitive ground-truth benchmark.
