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


# load options from the config file
PARAMS = P.get_parameters(
    ["%s/pipeline.yml" % os.path.splitext(__file__)[0],
     "pipeline.yml"])


###############################################################################
# Utility functions
###############################################################################
# determine the location of input files (reads)
try:
    PARAMS["location_fastq"]
except KeyError:
    DATADIR = "."
else:
    if PARAMS["location_fastq"] == 0:
        DATADIR = "."
    elif PARAMS["location_fastq"] == 1:
        DATADIR = "input.dir"
    else:
        DATADIR = PARAMS["location_fastq"]  # not recommended practice.

# Check that the input files correspond
# (this is set up so that input file suffixes can be altered if necessary)
FASTQ1_SUFFIX = 'fastq.1.gz'
FASTQ2_SUFFIX = 'fastq.2.gz'

fq1_regex = re.compile('(\S+).(%s)' % FASTQ1_SUFFIX)
mask1 = list(map(lambda x: bool(fq1_regex.match(x)), os.listdir(DATADIR)))
FASTQ1S = [os.path.join(DATADIR, i) \
           for i in itertools.compress(os.listdir(DATADIR), mask1)]

if sum(mask1):
    fq2_regex = re.compile('(\S+).(%s)' % FASTQ2_SUFFIX)
    mask2 = list(map(lambda x: bool(fq2_regex.match(x)), os.listdir(DATADIR)))
    fastq2s = [os.path.join(DATADIR, i) \
               for i in itertools.compress(os.listdir(DATADIR), mask2)]
    if sum(mask2):
        assert sum(mask1) == sum(mask2), 'Not all input files have pairs'
        IS_PAIRED = True
        fq1_stubs = [fq1_regex.match(x).group(1) for x in FASTQ1S]
        fq2_stubs = [fq2_regex.match(x).group(1) for x in fastq2s]
        assert sorted(fq1_stubs) == sorted(fq2_stubs), \
            "First and second read pair files do not correspond"        
    else:
        IS_PAIRED = False
else:
    raise ValueError("No input files detected... check the file suffixes"
                  " or specify input directory location in config file")


# Utility functions
def connect():
    '''utility function to connect to database.

    Use this method to connect to the pipeline database.
    Additional databases can be attached here as well.

    Returns an sqlite3 database handle.
    '''
    dbh = sqlite3.connect(PARAMS["database_name"])

    return dbh

def tool_exists(name):
    '''check that a tool is available in PATH'''
    return distutils.spawn.find_executable(name) 

def symlnk(inf, outf):
    try:
        os.symlink(os.path.abspath(inf), outf)
    except OSError as e:
        if e.errno == errno.EEXIST:
            os.remove(outf)
            os.symlink(inf, outf)


###############################################################################
# Deduplicate
###############################################################################
@follows(mkdir('reads_deduped.dir'))
@transform(FASTQ1S,
           regex(r'.+/(.+).%s' % FASTQ1_SUFFIX),
           r"reads_deduped.dir/\1_deduped.fastq.1.gz")
def removeDuplicates(fastq1, outfile):
    '''Filter exact duplicates, if specified in config file'''

    if IS_PAIRED:
        fastq2 = P.snip(fastq1, FASTQ1_SUFFIX) + FASTQ2_SUFFIX
        outfile1 = P.snip(outfile, '.gz') 
        outfile2 = P.snip(outfile1, '.fastq.1') + '.fastq.2'
        logfile = P.snip(outfile1, '.fastq.1') + '.log'
        cluster_file = P.snip(outfile1, '1') + '*.clstr'
        
        to_filter = PARAMS['cdhit_dedup']
        if to_filter:
            tmpf1 = P.get_temp_filename('.')
            tmpf2 = P.get_temp_filename('.')
            statement = ("zcat %(fastq1)s > %(tmpf1)s &&"
                         " zcat %(fastq2)s > %(tmpf2)s &&"
                         " cd-hit-dup"
                         "  -i %(tmpf1)s"
                         "  -i2 %(tmpf2)s"
                         "  -o %(outfile1)s"
                         "  -o2 %(outfile2)s"
                         "  %(cdhit_options)s"
                         " &> %(logfile)s &&"
                         " gzip %(outfile1)s &&"
                         " gzip %(outfile2)s &&"
                         " gzip %(logfile)s &&"
                         " rm -f %(tmpf1)s &&"
                         " rm -f %(tmpf2)s &&"
                         " rm -f %(cluster_file)s")
            P.run(statement, job_options=PARAMS['cdhit_run_options'])
        else:
            symlnk(fastq1, outfile)
            symlnk(fastq2, outfile2)

    else:
        outfile1 = P.snip(outfile, '.gz') 
        logfile = P.snip(outfile1, '.fastq.1') + '.log'
        cluster_file = P.snip(outfile1, '1') + '*.clstr'
        
        to_filter = PARAMS['preprocess_dedup']
        if to_filter:
            tmpf1 = P.getTempFilename('.')
            statement = ("zcat %(fastq1)s > %(tmpf1)s"
                         " cd-hit-dup"
                         "  -i %(tmpf1)s"
                         "  -o %(outfile1)s"
                         "  %(cdhit_options)s"
                         " &> %(logfile)s &&"
                         " gzip %(outfile1)s &&"
                         " gzip %(logfile)s &&"
                         " rm -f %(tmpf1)s &&"
                         " rm -f %(cluster_file)s")

            P.run(statement, job_options=PARAMS['cdhit_run_options'])      
        else:
            symlnk(fastq1, outfile)        

###############################################################################
# Remove Adapters
###############################################################################
@follows(mkdir('reads_adaptersRemoved.dir'))
@transform(removeDuplicates,
           regex('.+/(.+)_deduped.fastq.1.gz'),
           r'reads_adaptersRemoved.dir/\1_deadapt.fastq.1.gz')
def removeAdapters(fastq1, outfile1):
    '''Remove adapters using Trimmomatic'''

    if IS_PAIRED:
        fastq2 = P.snip(fastq1, FASTQ1_SUFFIX) + FASTQ2_SUFFIX
        outfile2 = P.snip(outfile1, '.fastq.1.gz') + '.fastq.2.gz'
        outf1_singletons = P.snip(outfile1, '.fastq.1.gz') + '.fastq.1s.gz'
        outf2_singletons = P.snip(outfile1, '.fastq.1.gz') + '.fastq.2s.gz'
        outf_singletons = P.snip(outfile1, '.fastq.1.gz') + '.fastq.3.gz'
        logfile = P.snip(outfile1, '.fastq.1.gz') + '.trim.log'
        logfile2 = P.snip(outfile1, '.fastq.1.gz') + '.log'
        
        statement = ("java -Xmx5g -jar %(trimmomatic_jar_path)s PE"
                     " -threads %(trimmomatic_n_threads)s"
                     " -phred%(phred_format)s"
                     " -trimlog %(logfile)s"
                     " %(fastq1)s" # input read 1
                     " %(fastq2)s" # input read 2
                     " %(outfile1)s" # output read 1
                     " %(outf1_singletons)s" # output unpaired read 1
                     " %(outfile2)s" # output read 2
                     " %(outf2_singletons)s" # output unpaired read 2
                     " ILLUMINACLIP:"
                     "%(trimmomatic_adapters)s:"
                     "%(trimmomatic_seed_mismatches)s:"
                     "%(trimmomatic_score_palendromic)s:"
                     "%(trimmomatic_score_simple)s:"
                     "%(trimmomatic_min_adapter_len)s:"
                     "%(trimmomatic_keep_both_reads)s"
                     " LEADING:%(trimmomatic_quality_leading)s"
                     " TRAILING:%(trimmomatic_quality_trailing)s"
                     " MINLEN:%(trimmomatic_minlen)s"
                     " &> %(logfile2)s &&"
                     " gzip -f %(logfile)s &&"
                     " cat %(outf1_singletons)s %(outf2_singletons)s "
                     "  > %(outf_singletons)s &&"
                     " rm -f %(outf1_singletons)s && rm -f %(outf2_singletons)s")

        P.run(statement, job_options = PARAMS['trimmomatic_run_options'])

    else:
        logfile = P.snip(outfile1, '.fastq.1.gz') + '.trim.log'
        logfile2 = P.snip(outfile1, '.fastq.1.gz') + '.log'
        
        statement = ("java -Xmx5g -jar %(trimmomatic_jar_path)s PE"
                     " -threads %(trimmomatic_n_threads)s"
                     " -phred%(phred_format)s"
                     " -trimlog %(logfile)s"
                     " %(fastq1)s" # input read 1
                     " %(outfile1)s" # output read 1
                     " ILLUMINACLIP:"
                     "%(trimmomatic_adapters)s:"
                     "%(trimmomatic_seed_mismatches)s:"
                     "%(trimmomatic_score_palendromic)s:"
                     "%(trimmomatic_score_simple)s"
                     "%(trimmomatic_min_adapter_len)s:"
                     "%(trimmomatic_keep_both_reads)s"
                     " LEADING:%(trimmomatic_quality_leading)s"
                     " TRAILING:%(trimmomatic_quality_trailing)s"
                     " MINLEN:%(trimmomatic_minlen)s"
                     " &> %(logfile2)s &&"
                     " gzip -f %(logfile)s")

        P.run(statement, job_options = PARAMS['trimmomatic_run_options'])



@follows(mkdir('reads_hostRemoved.dir'))
@transform(removeAdapters,
           regex('.+/(.+)_deadapt.fastq.1.gz'),
           r'reads_hostRemoved.dir/\1_dehost.fastq.1.gz')
def removeHostContamination(fastq1, outfile):
    '''Remove host contamination using bmtagger'''

    outf_host = P.snip(outfile, '_dehost.fastq.1.gz') + '_host.txt'
    outf_host_stub = P.snip(outf_host, '.txt') + '_toremove'

    # Whether to keep pair if a read is identified as host.
    if PARAMS['bmtagger_keep_pairs']:
        keep_pairs = True
        E.info("BMTagger: reads with a pair identified as host will be"
               " discarded")
    else:
        keep_pairs = False
        E.info("BMTagger: reads with a pair identified as host will be"
               " kept as singletons (assuming they are not also identified"
               " as host)")

    
    if IS_PAIRED:
        fastq2 = P.snip(fastq1, '.1.gz') + '.2.gz'
        fastq3 = P.snip(fastq1, '.1.gz') + '.3.gz'
        
        to_remove_paired = P.getTempFilename('.')            
        to_remove_singletons = P.getTempFilename('.')
        
        # In some cases, it may be desirable to screen against multiple hosts.
        indexes = zip(PARAMS['bmtagger_bitmask'].split(','),
                      PARAMS['bmtagger_srprism'].split(','))
        for n, indexes in enumerate(indexes, 1):
            n = str(n)
            bitmask, srprism = indexes

            # Screen the paired reads, then singletons
            tmpdir1 = P.getTempDir('.')
            tmpdir2 = P.getTempDir('.')
            
            tmpf1 = P.getTempFilename('.')
            tmpf2 = P.getTempFilename('.')
            tmpf3 = P.getTempFilename('.')
    
            # bmtagger truncates fasta headers...  sed 's/[[:space:]]\+/__/g'
            # It won't accept... sed 's|[[:space:]].*$|/1|'
            # It also fails if fastq1 header differs from fastq2
            statement1 = ("zcat %(fastq1)s > %(tmpf1)s &&"
                          " zcat %(fastq2)s > %(tmpf2)s &&"
                          " bmtagger.sh"
                          "  -b %(bitmask)s"
                          "  -x %(srprism)s"
                          "  -T %(tmpdir1)s"
                          "  -q1" # Input is fastq
                          "  -1 %(tmpf1)s"
                          "  -2 %(tmpf2)s"
                          "  -o %(outf_host_stub)s_paired%(n)s"
                          "  &> %(outfile)s.log &&"
                          " cat %(outf_host_stub)s_paired%(n)s"
                          "  >> %(to_remove_paired)s &&"
                          " rm -rf %(tmpdir1)s %(tmpf1)s %(tmpf2)s"
                          "  %(outf_host_stub)s_paired%(n)s")

            # Screen the singletons
            if IOTools.openFile(fastq3).read(1):
                statement2 = ("zcat %(fastq3)s > %(tmpf3)s &&"
                              " bmtagger.sh"
                              "  -b %(bitmask)s"
                              "  -x %(srprism)s"
                              "  -T %(tmpdir2)s"
                              "  -q1" # Input is fastq
                              "  -1 %(tmpf3)s"
                              "  -o %(outf_host_stub)s_singletons%(n)s"
                              " &>> %(outfile)s.log &&"
                              " cat %(outf_host_stub)s_singletons%(n)s"
                              "  >> %(to_remove_singletons)s &&"
                              " rm -rf %(tmpdir2)s %(tmpf3)s"
                              "  %(outf_host_stub)s_singletons%(n)s")
            else:
                statement2 = ("touch  %(to_remove_singletons)s &&"
                              " rm -rf %(tmpdir2)s %(tmpf3)s")

            statement = " && ".join([statement1, statement2])

            P.run(statement, job_options = PARAMS['bmtagger_run_options'])
            
        # Drop host contaminated reads
        # A hack due to the fact that BMTagger truncates fastq identifiers
        drop_script = os.path.join(os.path.splitext(__file__)[0],
                                   'drop_fastqs.py')
        
        fastq1_out = outfile
        fastq2_out = P.snip(outfile, '.1.gz') + '.2.gz'
        fastq3_out = P.snip(outfile, '.1.gz') + '.3.gz'

        fastq1_host = P.snip(outfile, '_dehost.fastq.1.gz') + '_host.fastq.1.gz'
        fastq2_host = P.snip(outfile, '_dehost.fastq.1.gz') + '_host.fastq.2.gz'
        fastq3_host = P.snip(outfile, '_dehost.fastq.1.gz') + '_host.fastq.3.gz'
    
        statement = ("python %(drop_script)s"
                     " --fastq1 %(fastq1)s"
                     " --fastq2 %(fastq2)s"
                     " --fastq3 %(fastq3)s"
                     " --to-drop-paired %(to_remove_paired)s"
                     " --to-drop-single %(to_remove_singletons)s"
                     " --fastq-out1 %(fastq1_out)s"
                     " --fastq-out2 %(fastq2_out)s"
                     " --fastq-out3 %(fastq3_out)s"
                     " --fastq-drop1 %(fastq1_host)s"
                     " --fastq-drop2 %(fastq2_host)s"
                     " --fastq-drop3 %(fastq3_host)s"
                     " &>> %(outfile)s.log")

        P.run(statement)
        
        os.unlink(to_remove_paired)
        os.unlink(to_remove_singletons)

        
    else:
        indexes = zip(PARAMS['bmtagger_bitmask'].split(','),
                      PARAMS['bmtagger_srprism'].split(','))
        to_remove = P.getTempFilename('.')
        
        for n, indexes in enumerate(indexes, 1):
            n = str(n)
            bitmask, srprism = indexes
            # Screen the singletons
            tmpdir1 = P.getTempDir('.')
            tmpf = P.getTempFilename('.')
            
            statement = ("zcat %(fastq1)s > %(tmpf)s &&"
                         " bmtagger.sh"
                         "  -b %(bitmask)s"
                         "  -x %(srprism)s"
                         "  -T %(tmpdir1)s"
                         "  -q1" # Input is fastq
                         "  -1 %(tmpf)s"
                         "  -o %(outf_host_stub)s_%(n)s"
                         "  &>> %(outfile)s.log &&"
                         " cat %(outf_host_stub)s_%(n)s >> %(to_remove)s"
                         " rm -rf %(tmpdir1)s %(tmpf)s %(outf_host_stub)s_%(n)s")

            P.run(statement, job_options = PARAMS['bmtagger_run_options'])
            

        # Drop host contaminated reads
        drop_script = ps.path.join(os.path.splitext(__file__)[0],
                                   'drop_single_fastqs.py')

        fastq_host = P.snip(outfile, '_dehost.fastq.1.gz') + '_host.fastq.1.gz'
        
        statement = ("python %(drop_script)s"
                     " --fastq1 %(fastq1)s"
                     " --to-drop-single %(to_remove)s"
                     " --fastq-out1 %(outfile)s"
                     " --fastq-drop1 %(fastq_host)s"
                     " &>> %(outfile)s.log")
        P.run(statement)
        
        os.unlink(to_remove)


@follows(mkdir('reads_dusted.dir'))
@transform(removeHostContamination,
           regex('.+/(.+)_dehost.fastq.1.gz'),
           r'reads_dusted.dir/\1_masked.fastq.1.gz')
def maskLowComplexity(fastq1, outfile):
    '''Either softmask low complexity regions, or remove reads with a large
    proportion of low complexity. 

    Uses BBTools scripts bbduk.sh (removal), or bbmask.sh. 

    Entropy is calculated as shannon entropy for of kmers with a specified size
    within a sliding window. Ranges from 0: mask nothing, 0.0001: mask
    homopolymers, 1: mask everything.
    '''

    bb_options= ' '.join(PARAMS['dust_options'].split(','))

    # bbmap assumes the file format based on the output being *fq.gz
    # I can't find any instructions as to how to override this.   
    if IS_PAIRED:
        fastq2 = P.snip(fastq1, '.1.gz') + '.2.gz'
        fastq3 = P.snip(fastq1, '.1.gz') + '.3.gz'

        outfile1 = P.snip(outfile, '.1.gz') + '.1.fq.gz'
        outfile2 = P.snip(outfile, '.1.gz') + '.2.fq.gz'
        outfile3 = P.snip(outfile, '.1.gz') + '.3.fq.gz'

        out_disc1 = P.snip(outfile, '_masked.fastq.1.gz') + '_discarded.fastq.1.fq.gz'
        out_disc2 = P.snip(outfile, '_masked.fastq.1.gz') + '_discarded.fastq.2.fq.gz'
        out_disc3 = P.snip(outfile, '_masked.fastq.1.gz') + '_discarded.fastq.3.fq.gz'
        
        if PARAMS['dust_discard_low_complexity']:
            statement1 = ("bbduk.sh"
                          "  in=%(fastq1)s"
                          "  in2=%(fastq2)s"
                          "  out=%(outfile1)s"
                          "  out2=%(outfile2)s"
                          "  outm=%(out_disc1)s"
                          "  outm2=%(out_disc2)s"
                          "  entropy=%(dust_entropy)s"
                          "  threads=%(dust_threads)s"
                          "  %(bb_options)s"
                          "  &> %(outfile)s.log")
            if IOTools.openFile(fastq3).read(1):
                statement2 = (" bbduk.sh"
                              "  in=%(fastq3)s"
                              "  out=%(outfile3)s"
                              "  outm=%(out_disc3)s"
                              "  entropy=%(dust_entropy)s"
                              "  threads=%(dust_threads)s"
                              "  %(bb_options)s"
                              "  &>> %(outfile)s.log")
            else:
                statement2 = (" touch %(outfile3)s  %(out_disc3)s")

            statement = " && ".join([statement1, statement2])
            
            P.run(statement, job_options=PARAMS['dust_run_options'])

        else:
            statement1 = ("bbmask.sh"
                          "  in=%(fastq1)s"
                          "  out=%(outfile1)s"
                          "  entropy=%(dust_entropy)s"
                          "  threads=%(dust_threads)s"
                          "  overwrite=t"
                          "  lowercase=t"
                          "  %(bb_options)s"
                          "  &> %(outfile)s.log &&"
                          " bbmask.sh"
                          "  in=%(fastq2)s"
                          "  out=%(outfile2)s"
                          "  entropy=%(dust_entropy)s"
                          "  threads=%(dust_threads)s"
                          "  overwrite=t"
                          "  lowercase=t"
                          "  %(bb_options)s"
                          "  &>> %(outfile)s.log")
            if IOTools.openFile(fastq3).read(1):           
                statement2 = (" bbmask.sh"
                              "  in=%(fastq3)s"
                              "  out=%(outfile3)s"
                              "  entropy=%(dust_entropy)s"
                              "  threads=%(dust_threads)s"
                              "  overwrite=t"
                              "  lowercase=t"
                              "  %(bb_options)s"
                              "  &>> %(outfile)s.log")
            else:
                statement2 = (" touch %(outfile3)s")

            statement = " && ".join([statement1, statement2])

            P.run(statement, job_options=PARAMS['dust_run_options'])

        # Renaming files because of bbmap idiosyncracies
        of1 = P.snip(outfile1, '.fq.gz') + '.gz'
        of2 = P.snip(outfile2, '.fq.gz') + '.gz'
        of3 = P.snip(outfile3, '.fq.gz') + '.gz'
        os.rename(outfile1, of1)
        os.rename(outfile2, of2)
        os.rename(outfile3, of3)

        if PARAMS['dust_discard_low_complexity']:
            od1 = P.snip(out_disc1, '.fq.gz') + '.gz'
            od2 = P.snip(out_disc2, '.fq.gz') + '.gz'
            od3 = P.snip(out_disc3, '.fq.gz') + '.gz'
            os.rename(out_disc1, od1)
            os.rename(out_disc2, od2)
            os.rename(out_disc3, od3)

    else:
        outfile1 = P.snip(outfile, '.gz') + '.fq.gz'
        out_disc = P.snip(outfile, '_masked.fastq.1.gz') + '_discarded.fastq.1.fq.gz'
        
        if PARAMS['dust_discard_low_complexity']:
            statement = ("bbduk.sh"
                         " in=%(fastq1)s"
                         " out=%(outfile1)s"
                         " outm=%(out_disc)s"
                         " entropy=%(dust_entropy)s"
                         " threads=%(dust_threads)s"
                         " lowercase=t"
                         " %(bb_options)s"
                         " &> %(outfile)s.log")

            P.run(statement, job_options=PARAMS['dust_run_options'])

        else:
            statement = ("bbmask.sh"
                         " in=%(fastq1)s"
                         " out=%(outfile1)s"
                         " entropy=%(dust_entropy)s"
                         " threads=%(dust_threads)s"
                         " lowercase=t"
                         " %(bb_options)s"
                         " &> %(outfile.log")

            P.run(statement, job_options=PARAMS['dust_run_options'])

        os.rename(outfile1, outfile)
        if PARAMS['dust_discard_low_complexity']:
            od1 = P.snip(out_disc, '.fq.gz') + '.gz'
            os.rename(out_disc, od1)
        
###############################################################################
# Summary Metrics
###############################################################################
# @transform(removeAdapters, '.fastq.1.gz', '_histogram.png')
# def plotDeadaptLengthDistribution(infile, outfile):
#     '''Create a histogram of length distributions'''
@follows(mkdir('read_count_summary.dir'))
@transform(FASTQ1S,
           regex(r'.+/(.+).%s' % FASTQ1_SUFFIX),
           r"read_count_summary.dir/\1_input.nreads")
def countInputReads(infile, outfile):
    
    statement = ("zcat %(infile)s |"
                 " awk '{n+=1;} END {printf(n/4);}'"
                 " > %(outfile)s")

    P.run(statement)


@follows(countInputReads)
@transform([removeDuplicates, removeAdapters,
            removeHostContamination, maskLowComplexity],
           regex('.+/(.+).fastq.1.gz'),
           r'read_count_summary.dir/\1.nreads')
def countOutputReads(infile, outfile):
    '''Count the number of reads in the output files'''    
    statement = ("zcat %(infile)s |"
                 " awk '{n+=1;} END {printf(n/4);}'"
                 " > %(outfile)s")

    P.run(statement)


@collate([countInputReads, countOutputReads],
         regex('(.+)_(input|deduped|deadapt|dehost|masked).nreads'),
         r'\1_read_count_summary.tsv')
def collateReadCounts(infiles, outfile):
    '''Collate read counts for each sample'''

    infiles = ' '.join(infiles)
    
    statement = ("cgat combine_tables"
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

    with IOTools.openFile(outfile, 'w') as outf:
        outf.write("sample_id\tinput_reads\toutput_reads\tduplicates\t"
                   "adapter_contamination\thost\tlow_complexity\t"
                   "duplicates_percent\tadapters_percent\thost_percent\t"
                   "low_complexity_perc\tremaining_percent\n")
        for infile in infiles:
            sample_id = P.snip(os.path.basename(infile),
                               '_read_count_summary.tsv')
            E.info('Processing sample %s' % sample_id)
            
            df = pd.read_table(infile, index_col=0, header=None)
            deadapt = df.loc['deadapt', 1]
            deduped = df.loc['deduped', 1]
            dehost = df.loc['dehost', 1]
            masked = df.loc['masked', 1]
            input_reads = df.loc['input', 1]
            
            lost_dup = input_reads - deduped
            lost_adapt = deduped - deadapt
            lost_host = deadapt - dehost
            lost_mask = dehost - masked

            lost_dup_perc = round(lost_dup/float(input_reads) * 100, 2)
            lost_adapt_perc = round(lost_adapt/float(input_reads) * 100, 2)
            lost_host_perc = round(lost_host/float(input_reads) * 100, 2)
            lost_mask_perc = round(lost_mask/float(input_reads) * 100, 2)
            output_perc = round(masked/float(input_reads) * 100, 2)
            
            outf.write('\t'.join(map(str, [sample_id, input_reads, masked,
                                           lost_dup, lost_adapt,
                                           lost_host, lost_mask,
                                           lost_dup_perc,
                                           lost_adapt_perc,
                                           lost_host_perc,
                                           lost_mask_perc,
                                           output_perc])) + '\n')
            

def main(argv=None):
    if argv is None:
        argv = sys.argv
    P.main(argv)


if __name__ == "__main__":
    sys.exit(P.main(sys.argv))    