# DNNTuplesAK8

## Setup
```bash
cmsrel CMSSW_10_6_30
cd CMSSW_10_6_30/src
cmsenv

# use an updated onnxruntime package
bash <(curl -s https://raw.githubusercontent.com/hypnotismer/DNNTuples/dev-UL-VR/Ntupler/scripts/install_onnxruntime.sh)

# clone this repo into "DeepNTuples" directory
git clone git@github.com:hypnotismer/DNNTuples.git DeepNTuples -b dev-UL-VR

scram b -j8
```

## Variable-R training tuples (`dev-UL-VR`)

`Ntupler/test/DeepNtuplizerVR.py` reclusters one raw PUPPI anti-kT jet
collection per job.  The `jetRadius` option is the radius in tenths and must be
an integer from 2 through 15.  For example, an interactive AK6 test is:

```bash
cmsRun Ntupler/test/DeepNtuplizerVR.py \
  jetRadius=6 \
  inputFiles=file:/path/to/input.root \
  outputFile=output_AK6.root \
  maxEvents=100
```

No JEC payload or jet kinematic selection is applied during tuple production;
phase-space cuts should be made offline after aligning entries across radii.
Every output row stores `fj_jetR`, `run_no`, `lumi_no`, and the 64-bit
`event_no`.  `H_ggg` is assigned only when all three direct gluon daughters are
contained within the selected jet radius; its class index immediately follows
`H_gg`.

The CRAB helper can create independent tasks and ROOT outputs for all radii in
one command.  Task request names and output dataset tags receive an `AK2`
through `AK15` suffix:

```bash
cd Ntupler/run
python crab.py \
  --set-input-dataset \
  -p ../test/DeepNtuplizerVR.py \
  --jet-radii 2 3 4 5 6 7 8 9 10 11 12 13 14 15 \
  --site T2_CH_CERN \
  -o /store/user/$USER/DeepNtuples/VR-v1 \
  -t DeepNtuplesVR-v1 \
  --no-publication \
  -i samples/UL17/ak8/signals.conf \
  -s FileBased -n 1 \
  --work-area crab_projects_VR-v1 \
  --send-external \
  --dryrun
```

Inspect the generated configurations first, then remove `--dryrun` to submit.

<!-- 
## Submit jobs via CRAB

**Step 0**: switch to the crab production directory and set up grid proxy, CRAB environment, etc.

```bash
cd $CMSSW_BASE/src/DeepNTuples/Ntupler/run
# set up grid proxy
voms-proxy-init -rfc -voms cms --valid 168:00
# set up CRAB env (must be done after cmsenv)
source /cvmfs/cms.cern.ch/common/crab-setup.sh
```

**Step 1**: use the `crab.py` script to submit the CRAB jobs:

`python crab.py --set-input-dataset -p ../test/DeepNtuplizerAK8.py --site T2_CH_CERN -o /store/user/$USER/DeepNtuples/[version] -t DeepNtuplesAK8-[version] --no-publication -i [ABC].conf -s FileBased -n 5 --work-area crab_projects_[ABC] --send-external [--input_files JEC.db] --dryrun`

These command will perform a "dryrun" to print out the CRAB configuration files. Please check everything is correct (e.g., the output path, version number, requested number of cores, etc.) before submitting the actual jobs. To actually submit the jobs to CRAB, just remove the `--dryrun` option at the end.

**[Note] For the QCD samples use `-n 1 --max-units 20` to run one file per job, and limit the total files per job to 20.**


**Step 2**: check job status

The status of the CRAB jobs can be checked with:

```bash
./crab.py --status --work-area crab_projects_[ABC]
```

Note that this will also resubmit failed jobs automatically.

The crab dashboard can also be used to get a quick overview of the job status:
`https://dashb-cms-job.cern.ch/dashboard/templates/task-analysis`

More options of this `crab.py` script can be found with:

```bash
./crab.py -h
``` -->
