"""
================================
Preprocess shotgun sequence data
================================


Overview
========

This pipeline is based on the original HMP protocol for
preprocessing mWGS reads: 

1) Remove identical duplicates on the assumption that they are PCR dups. 
2) Trim adapters 
3) Optionally remove rRNA reads (for metatranscriptome)
4) Remove host reads 
5) Either softmask or remove low complexity

Configuration
=============
The pipeline requires a configured :file:`pipeline.yml` file.

Default configuration files can be generated by executing:
    
    python <srcdir>/pipeline_preprocessing.py config

Dependencies
============

cdhit-dup
trimmomatic
sortmeRNA
bmtagger
bbduk

source /well/kir/config/modules.sh
module load CD-HIT/4.8.1-GCC-9.3.0
module load CD-HIT-auxtools/4.8.1-GCC-9.3.0
module load bmtagger/3.101-gompi-2020a
module load Trimmomatic/0.39-Java-11
module load BBMap/38.90-GCC-9.3.0
module load SortMeRNA/4.3.4
module load SAMtools/1.10-GCC-9.3.0
module load HISAT2/2.2.1-foss-2020a
module load BEDTools/2.30.0-GCC-12.2.0
Code
====

"""
from ruffus import *
from cgatcore import pipeline as P
from cgatcore import iotools as IOTools
from cgatcore import experiment as E

import cgat.Fastq as Fastq

import os,sys,re
import sqlite3
import itertools
import distutils
import pandas as pd

import ocmsshotgun.modules.Utility as utility
import ocmsshotgun.modules.PreProcess as pp

# set up params
PARAMS = P.get_parameters(["pipeline.yml"])

indir = PARAMS.get("input.dir", "input.dir")
# check that input files correspond
FASTQ1S = utility.check_input(indir)

###############################################################################
# Deduplicate
###############################################################################
@follows(mkdir('reads_deduped.dir'))
@transform(FASTQ1S,
           regex(fr'{indir}/(.+).fastq.1.gz'),
           r"reads_deduped.dir/\1_deduped.fastq.1.gz")
def removeDuplicates(fastq1, outfile):
    '''Filter exact duplicates, if specified in config file'''
    statement = pp.cdhit(fastq1, outfile, **PARAMS).buildStatement()

    P.run(statement,
          job_threads=PARAMS['cdhit_job_threads'], 
          job_memory=PARAMS['cdhit_job_memory'],
          job_options=PARAMS.get('cdhit_job_options',''))

###############################################################################
# Remove Adapters
###############################################################################
@follows(mkdir('reads_adaptersRemoved.dir'))
@transform(removeDuplicates,
           regex(r'.+/(.+)_deduped.fastq.1.gz'),
           r'reads_adaptersRemoved.dir/\1_deadapt.fastq.1.gz')
def removeAdapters(fastq1, outfile1):
    '''Remove adapters using Trimmomatic'''

    statement = pp.trimmomatic(fastq1, outfile1, **PARAMS).buildStatement()

    P.run(statement,
          job_threads = PARAMS['trimmomatic_job_threads'],
          job_memory = PARAMS['trimmomatic_job_memory'],
          job_options = PARAMS.get('trimmomatic_job_options', ''))


###############################################################################
# Remove Contamination
###############################################################################
@follows(mkdir('reads_rrnaRemoved.dir'))
@transform(removeAdapters,
           regex(r'.+/(.+)_deadapt.fastq.1.gz'),
           r'reads_rrnaRemoved.dir/\1_rRNAremoved.fastq.1.gz')
def removeRibosomalRNA(fastq1, outfile):
    '''Remove ribosomal RNA using sortMeRNA'''
    

    if PARAMS['data_type'] == 'metatranscriptome':
        tool = pp.runSortMeRNA(fastq1, outfile, **PARAMS)
        
        # Logging
        runfiles = '\t'.join([os.path.basename(x) for x in (tool.fastq1, \
                                                            tool.fastq2, \
                                                            tool.fastq3) if x])
        E.info("Running sortMeRNA for files: {}".format(runfiles))

        # run sortmerna
        statement = tool.buildStatement()
        P.run(statement, 
              job_threads=PARAMS["sortmerna_job_threads"],
              job_memory=PARAMS["sortmerna_job_memory"],
              job_options=PARAMS.get("sortmerna_job_options",''))
        
        # perform postprocessing steps
        tool.postProcess()
    else:
        assert PARAMS['data_type'] == 'metagenome', \
            'Unrecognised data type: {}'.format(PARAMS['data_type'])
        
        inf1 = fastq1
        inf2 = P.snip(inf1, '.fastq.1.gz') + '.fastq.2.gz'
        inf3 = P.snip(inf1, '.fastq.1.gz') + '.fastq.3.gz'

        outf1 = outfile
        outf2 = P.snip(outf1, '.fastq.1.gz') + '.fastq.2.gz'
        outf3 = P.snip(outf1, '.fastq.1.gz') + '.fastq.3.gz'
        
        utility.symlnk(inf1, outf1)
        if os.path.exists(inf2):
            utility.symlnk(inf2, outf2)
        if os.path.exists(inf3):
            utility.symlnk(inf3, outf3)


@follows(mkdir('reads_rrnaClassified.dir'))
@transform(removeAdapters,
           regex(r'.+/(.+)_deadapt.fastq.1.gz'),
           r'reads_rrnaClassified.dir/\1_otu_map.txt')
def classifyRibosomalRNA(fastq1, outfile):

    assert PARAMS['data_type'] == 'metatranscriptome', \
        "Can't run rRNA classification on mWGS data..."

    tool = pp.createSortMeRNAOTUs(fastq1, 
                                  outfile, 
                                  **PARAMS)
    
    statement = tool.buildStatement()
    P.run(statement, 
          job_threads=PARAMS["sortmerna_job_threads"],
          job_memory=PARAMS["sortmerna_job_memory"],
          job_options=PARAMS.get("sortmerna_job_options",''))
    

@transform(classifyRibosomalRNA, suffix('_map.txt'), 's.tsv.gz')
def summarizeRibosomalRNAClassification(infile, outfile):
    '''Count the number of reads mapping to each taxon'''
    
    sample_id = P.snip(infile, '_otu_map.txt', strip_path=True)
    
    with IOTools.open_file(outfile, 'w') as outf:
        outf.write('taxonomy\t%s\n' % sample_id)
        for otu in IOTools.open_file(infile):
            taxonomy = otu.split()[0]
            reads = otu.split()[1:]
            outf.write(taxonomy + '\t' + str(len(reads)) + '\n')


@merge(summarizeRibosomalRNAClassification,
       'reads_rrnaClassified.dir/metatranscriptome_otus.tsv.gz')
def combineRNAClassification(infiles, outfile):
    '''Combine output of sortmerna read classification'''

    infiles = ' '.join(infiles)

    statement = ("cgat tables2table"
                 "  --log=%(outfile)s.log"
                 "  %(infiles)s |"
                 " gzip > %(outfile)s")
    P.run(statement, to_cluster=False)

################################################################################
# remove host sequences with bmtagger or hisat
################################################################################
@follows(mkdir('reads_hostRemoved.dir'))
@follows(removeRibosomalRNA)
@transform(removeRibosomalRNA,
           regex(r'reads_rrnaRemoved.dir/(\S+)_rRNAremoved.fastq.1.gz$'),
           r'reads_hostRemoved.dir/\1_dehost.fastq.1.gz')
def alignAndRemoveHost(infile,outfile): 
    '''Align and remove host sequences with bmtagger or HISAT2
    '''
    # bmtagger - aligns with srprism
    if PARAMS['host_tool']  == 'bmtagger':
        tool = pp.bmtagger(infile, outfile, **PARAMS)
        statements, tmpfiles = tool.buildStatement()

        # one statement for each host genome specified
        for statement in statements:
            P.run(statement, 
                job_threads=PARAMS['bmtagger_job_threads'], 
                job_memory=PARAMS['bmtagger_job_memory'],
                job_options=PARAMS.get('bmtagger_job_options',''))
        
        statement, to_unlink  = tool.postProcess(tmpfiles)
        P.run(statement)
        for f in to_unlink:
            os.unlink(f)
    # Align host sequences with HISAT2 and return mapped and unmapped reads
    # converts the output from sam to bam
    elif PARAMS['host_tool'] == 'hisat':
        tool = pp.hisat2(infile, outfile, **PARAMS)

        # build statement to run hisat2 and convert sam to bam
        statement = tool.hisat2bam()
        
        P.run(statement,
            job_threads = PARAMS["hisat2_job_threads"],
            job_memory = PARAMS["hisat2_job_memory"])
        
        # clean up sam files and hisat outputs
        statement = tool.postProcessPP()
        P.run(statement, without_cluster=True)

@active_if(PARAMS['host_tool'] == 'hisat')
@merge(alignAndRemoveHost,
       "reads_hostRemoved.dir/merged_hisat2_summary.tsv")
def mergeHisatSummary(infiles, outfile):
   # hisat summary logs
    logs = []
    for fq in infiles:
        fq_class = pp.utility.matchReference(fq, outfile, **PARAMS)
        log = fq.replace(f"_dehost{fq_class.fq1_suffix}", "_hisat2_summary.log")
        logs.append(log)
    tool = pp.hisat2(infiles[0], outfile, **PARAMS)
    tool.mergeHisatSummary(logs, outfile)

@active_if(PARAMS['host_tool'] == 'hisat')
@merge(alignAndRemoveHost,
       "reads_hostRemoved.dir/clean_up.log")
def cleanHisat(infiles, outfile):
    tool = pp.hisat2(infiles[0], outfile, **PARAMS)
    statement = tool.cleanPP(infiles, outfile)

    P.run(statement, without_cluster=True)

@follows(alignAndRemoveHost, mergeHisatSummary)
def removeHost():
    pass

###############################################################################
# Mask or Remove Low-complexity sequence
###############################################################################
@follows(mkdir('reads_dusted.dir'))
@transform(alignAndRemoveHost,
           regex(r'.+/(.+)_dehost.fastq.1.gz'),
           r'reads_dusted.dir/\1_masked.fastq.1.gz')
def maskLowComplexity(fastq1, outfile):
    '''Either softmask low complexity regions, or remove reads with a large
    proportion of low complexity. 

    Uses BBTools scripts bbduk.sh (removal), or bbmask.sh. 

    Entropy is calculated as shannon entropy for of kmers with a specified size
    within a sliding window. Ranges from 0: mask nothing, 0.0001: mask
    homopolymers, 1: mask everything.
    '''

    tool = pp.bbtools(fastq1, outfile, **PARAMS)
    
    statement = tool.buildStatement()
    P.run(statement, 
          job_threads=PARAMS['dust_job_threads'],
          job_memory=PARAMS['dust_job_memory'],
          job_options=PARAMS.get('dust_job_options', ''))
    
    tool.postProcess()
    
###############################################################################
# Summary Metrics
###############################################################################
# @transform(removeAdapters, '.fastq.1.gz', '_histogram.png')
# def plotDeadaptLengthDistribution(infile, outfile):
#     '''Create a histogram of length distributions'''
@follows(mkdir('read_count_summary.dir'))
@transform(FASTQ1S,
           regex(r'.+/(.+).fastq.1.gz'),
           r"read_count_summary.dir/\1_input.nreads")
def countInputReads(infile, outfile):
    
    outf = open(outfile, "w")
    outf.write("nreads\n")
    outf.close()
    statement = ("zcat %(infile)s |"
                 " awk '{n+=1;} END {printf(n/4\"\\n\");}'"
                 " >> %(outfile)s")

    P.run(statement)


@follows(countInputReads)
@transform([removeDuplicates, removeAdapters, removeRibosomalRNA,
            alignAndRemoveHost, maskLowComplexity],
           regex(r'.+/(.+).fastq.1.gz'),
           r'read_count_summary.dir/\1.nreads')
def countOutputReads(infile, outfile):
    '''Count the number of reads in the output files'''    
    
    outf = open(outfile, "w")
    outf.write("nreads\n")
    outf.close()
    statement = ("zcat %(infile)s |"
                 " awk '{n+=1;} END {printf(n/4\"\\n\");}'"
                 " >> %(outfile)s")

    P.run(statement)

@collate([countInputReads, countOutputReads],
         regex(r'(.+)_(input|deduped|deadapt|dehost|rRNAremoved|masked).nreads'),
         r'\1_read_count_summary.tsv')
def collateReadCounts(infiles, outfile):
    '''Collate read counts for each sample'''

    infiles = ' '.join(infiles)
    
    statement = ("cgat tables2table"
                 " --cat Step"
                 " --regex-filename='.+_(.+)\.nreads'"
                 " --no-titles"
                 " --log=%(outfile)s.log"
                 " %(infiles)s"
                 " > %(outfile)s")
    P.run(statement)
    
@merge(collateReadCounts, 'processing_summary.tsv')
def summarizeReadCounts(infiles, outfile):
    '''Calculate the number of reads lost at each step for each sample'''
    pp.summariseReadCounts(infiles, outfile)

@follows(summarizeReadCounts)
def full():
    pass

def main(argv=None):
    if argv is None:
        argv = sys.argv
    P.main(argv)


if __name__ == "__main__":
    sys.exit(P.main(sys.argv))    
