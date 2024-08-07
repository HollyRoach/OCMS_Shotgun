# OCMS pipelines for shotgun metagenomic data analysis
This repository contains a series of pipelines used for processing shotgun metagenomic data. Pipelines are written within the [CGAT framework](https://github.com/cgat-developers/cgat-core). OMCS_Shotgun has a command line interface, and can be installed and executed as a stand alone command line tool. OCMS_Shotgun is primarily written for usage within the OCMS on our HPC system, however, it can be used on other HPC systems, or used locally.

## Install
Clone the OCMS_Shotgun repository and install using pip, ideally within a python virtual environment.

```
# Download the repo
git clone https://github.com/OxfordCMS/OCMS_Shotgun.git

# Activate python virtual environment (if applicable) and install OCMS_Shotgun
cd OCMS_Shotgun
pip install .
```

## Pipeline Environments
Each pipeline has it's own set of dependencies. It is recommended that you only load the tools necessary for the pipeline being used. If you are working within the BMRC HPC, you can load the pipeline modulefile. See the OCMS modulefiles SOP for more details. If you are not working within the BMRC, please ensure that

## Quick Start
All pipelines are written to be used within a HPC system, but can be run using the `--local` flag to run locally. 

Set up the pipeline configuration file within your working directory.

```
ocms_shotgun preprocess config
```

You can see the pipeline tasks with `show full`. 

```
ocms_shotgun preprocess show full
```

Run pipeline individual pipeline tasks with `make` followed by the pipeline task or run all pipeline tasks with `make full`

```
ocms_shotgun kraken2 make full -p 20 -v 5
```

## Pipeline Preprocess
This pipeline pre-processes shotgun metagenome or metatranscriptome data. It performes the following:

* summarise raw input read counts
* remove duplicate sequences with Cdhit
* removeAdapters with Trimmomatic
* remove rRNA with SortMeRNA
* remove host reads with SortMeRNA
* mask low complexity reads with bmtagger
* summrise preprocessed read counts

### Dependencies
```
module load pipelines/preprocess

OR

#### modules for using GCCcore/9.3.9 ####

module load CD-HIT/4.8.1-GCC-9.3.0
module load CD-HIT-auxtools/4.8.1-GCC-9.3.0
module load bmtagger/3.101-gompi-2020a
module load Trimmomatic/0.39-Java-11
module load BBMap/38.90-GCC-9.3.0
module load SortMeRNA/4.3.4-GCC-9.3.0
module load BLAST+/2.10.1-gompi-2020a

#### modules for using GCCcore/12.2.0 ####

module load CD-HIT/4.8.1-GCC-12.2.0
module load CD-HIT-auxtools/4.8.1-GCC-12.2.0
module load bmtagger/3.101-gompi-2022b
module load Trimmomatic/0.39-Java-11
module load BBMap/39.01-GCC-12.2.0 
module load SortMeRNA/4.3.4
module load SAMtools/1.17-GCC-12.2.0 
module load SRPRISM/3.3.2-GCCcore-12.2.0
module load BLAST+/2.14.0-gompi-2022b
```

### Configuration
Initiate the configuration file.

```
ocms_shotgun preprocess config
```

### Input files
Pipeline preprocess takes in single or paired end reads. Input files should use the notation `fastq.1.gz`, `fastq.2.gz`. Input files should be located in the working directory, alternatively, an input directory called `input.dir` can be specified in the yml with:

```
# pipeline.yml
location_fastq: 1
```

### Pipeline tasks

```
Task = "mkdir('read_count_summary.dir')   before pipeline_preprocess.countInputReads "
Task = 'pipeline_preprocess.countInputReads'
Task = "mkdir('reads_deduped.dir')   before pipeline_preprocess.removeDuplicates "
Task = 'pipeline_preprocess.removeDuplicates'
Task = "mkdir('reads_adaptersRemoved.dir')   before pipeline_preprocess.removeAdapters "
Task = 'pipeline_preprocess.removeAdapters'
Task = "mkdir('reads_rrnaRemoved.dir')   before pipeline_preprocess.removeRibosomalRNA "
Task = 'pipeline_preprocess.removeRibosomalRNA'
Task = "mkdir('reads_hostRemoved.dir')   before pipeline_preprocess.removeHost "
Task = 'pipeline_preprocess.removeHost'                                                 
Task = "mkdir('reads_dusted.dir')   before pipeline_preprocess.maskLowComplexity "
Task = 'pipeline_preprocess.maskLowComplexity'
Task = 'pipeline_preprocess.countOutputReads'
Task = 'pipeline_preprocess.collateReadCounts'
Task = 'pipeline_preprocess.summarizeReadCounts'
Task = 'pipeline_preprocess.full'         
```

### Run pipeline_preprocess
The pipeline must have input fastq files with the notation `.fastq.1.gz` and `pipeline.yml` in working directory. Set the number of jobs `-p` equal to the number of samples.

```
ocms_shotgun preprocess make full -p 20 -v 5
```

### Output
```
```

## Pipeline Kraken2
Uses Kraken2 to classify paired-end reads
Uses Bracken to estimate abundances at every taxonomic level
Uses Taxonkit to generate a taxonomy file listing taxonomic lineage in mpa style

### Dependencies
Taxonkit requires NCBI taxonomy files, which can be downloaded from the [NCBI FTP](https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz). Path to directory of taxonomy files is specified in the `taxdump` parameter in the yml. 

```
module load pipelines/kraken2

OR

#### modules for using GCCcore/9.3.0 ####m
module load Kraken2/2.0.9-beta-gompi-2020a-Perl-5.30.2
module load Bracken/2.6.0-GCCcore-9.3.0
module load taxonkit/0.14.2

#### modules for using GCCcore/12.2.0 ####
module load Kraken2/2.1.2-gompi-2022b
module load Bracken/2.9-GCCcore-12.2.0
module load taxonkit/0.14.2
```

### Configuration
Initiate the configuration file.

```
ocms_shotgun kraken2 config
```

### Input files
Pipeline preprocess takes in single or paired end reads. Input files should use the notation `fastq.1.gz`, `fastq.2.gz`. Input files should be located in the working directory.

### Pipeline tasks

```
Task = "mkdir('taxonomy.dir')   before pipeline_kraken2.translateTaxonomy "
Task = "mkdir('bracken.dir')   before pipeline_kraken2.runBracken "
Task = 'pipeline_kraken2.runBracken'
Task = 'pipeline_kraken2.checkBrackenLevels'
Task = 'pipeline_kraken2.mergeBracken'
Task = 'pipeline_kraken2.translateTaxonomy'
Task = 'pipeline_kraken2.full'
```

### Run pipeline_kraken2
The pipeline must have input fastq files with the notation `.fastq.1.gz` and `pipeline.yml` in working directory. Set the number of jobs `-p` to 7 times the number of samples (so Bracken can be run on all taxonomic levels in parallel), however please be mindful of the number of jobs.

```
ocms_shotgun kraken2 -p 140 -v 5
```

### Output
```
# classified reads
kraken.dir/

# estimated abundances
bracken.dir/

# showing taxonomy as mpa-styled lineages
taxonomy.dir/
```

## Pipeline Concatfastq
This pipelines concatenates paired-end reads into one file. This is helpful when running Humann3.

### Dependencies
No dependencies

### Configuration
No configuration file needed

### Input files
Paired end reads should end in the notation `fastq.1.gz` and `fastq.2.gz`. Input files located in working directory.

### Run pipeline_concatfastq
Set number of jobs `-p` to the number of samples

```
ocms_shotgun concatfastq make full -p 20 -v 5
```

### Output
Concatenated fastq files located in `concat.dir/`

## Pipeline Humann3
This pipeline performs functional profiling of fastq files using Humann3.

### Dependencies
This pipeline was written for Humann3 v3.8 and Metaphlan 3.1. If you're not working within BMRC, Humann3 and Metaphlan3 need to be installed according to their developers' instructions. 

```
module load pipelines/humann3

OR

#### modules for using GCCcore/9.3.0 ####
module load Bowtie2/2.4.1-GCC-9.3.0
module load DIAMOND/2.0.15-GCC-9.3.0
module load Pandoc/2.13
module load X11/20200222-GCCcore-9.3.0
module load GLPK/4.65-GCCcore-9.3.0
module load R/4.2.1-foss-2020a-bare

#### modules for using GCCcore/12.2.0 ####
module load Bowtie2/2.5.1-GCC-12.2.0
module load DIAMOND/2.1.8-GCC-12.2.0
module load Pandoc/2.5
module load X11/20221110-GCCcore-12.2.0
module load GLPK/5.0-GCCcore-12.2.0
module load R/4.3.1-foss-2022b-bare
```

### Configuration
Initiate configuration file

```
ocms_shotgun humann3 config
```

### Input files
Humann3 takes in single end reads. If you have paired-end reads, paired-ends need to be concatenated into one file. Concatenating paired-end fastqs can be done with ` pipeline_concatfastq`. Input files should end in the notation `fastq.gz`, located in the working directory.

### Pipeline tasks

```
Task = "mkdir('humann3.dir')   before pipeline_humann3.runHumann3 "
Task = 'pipeline_humann3.runHumann3'
Task = 'pipeline_humann3.mergePathCoverage'
Task = 'pipeline_humann3.mergePathAbundance'
Task = 'pipeline_humann3.mergeGeneFamilies'
Task = 'pipeline_humann3.mergeMetaphlan'
Task = 'pipeline_humann3.splitMetaphlan'
```

### Run pipeline_humann3
Set number of jobs `-p` to number of samples.

```
ocms_shotgun humann3 make full -p 20 -v 5
```

### Output
Humann3 outputs for each sample are in their respective sample directories under `humann.dir`.
Humann3 outputs are automatically compressed once they are created. Metaphlan taxa abundances (`<sample>_metaphlan_bugs_list.tsv.gz` are moved out of the temporary direcory created by Humann3 and compressed. Metaphlan taxa abundances are split according by taxonomic levels. Each of the Humann3 outputs for all samples are merged into their respective files `merged_genefamilies.tsv`, `merged_pathabundance.tsv`, `merged_pathcoverage.tsv`, `merged_metaphlan.tsv`.

```
humann.dir/
    |- sample1/
    |- sample2/
    ...
    |- samplen/
        |- samplen_genefamilies.tsv.gz
	|- samplen_pathabundance.tsv.gz
	|- samplen_pathcoverage.tsv.gz
	|- samplen_metaphlan_bugs_list.tsv.gz
	|- samplen_humann_temp.tar.gz
    |- merged_genefamilies.tsv
    |- merged_metaphlan.tsv
    |- merged_metaphlan_class.tsv
    |- merged_metaphlan_family.tsv
    |- merged_metaphlan_genus.tsv
    |- merged_metaphlan_order.tsv
    |- merged_metaphlan_phylum.tsv
    |- merged_metaphlan_species.tsv
    |- merged_pathabundance.tsv
    |- merged_pathcoverage.tsv
```

### Report
Generate a report on humann3 results

```
ocms_shotgun humann3 make build_report
```
