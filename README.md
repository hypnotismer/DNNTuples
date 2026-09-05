# DNNTuplesAK8

For the lossless multi-R `dev-UL-VRslim` production entry point, shared
Events/Jets format, reader and merger, see [VRSLIM.md](VRSLIM.md).

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
collection per job.  The `jetRadius` option is the physical radius itself and
accepts any positive finite value.  For example, an interactive R=0.25 test is:

Values are no longer encoded in tenths: use `jetRadius=0.2` for R=0.2;
`jetRadius=2` now means the physical radius R=2.

```bash
cmsRun Ntupler/test/DeepNtuplizerVR.py \
  jetRadius=0.25 \
  jetPtMin=200 \
  jetPreselectionPtMin=170 \
  genJetPtMin=100 \
  inputFiles=file:/path/to/input.root \
  outputFile=output_AK6.root \
  maxEvents=100
```

No JEC payload is applied.  The production preserves the staged pT thresholds
of the `dev-UL-hww` AK8 workflow: 100 GeV for GenJet and SoftDrop producers,
170 GeV for reco-jet preselection, and 200 GeV for jets written to the tuple.
These thresholds are independent of R, and there is no eta or rapidity cut.
The existing signal miniAOD starts at a 150 GeV resonance-pT
scale while the QCD production starts at 170 GeV, so lowering the tuple cut
would not extend the intended generated phase space.  Low-mass resonances are
instead resolved with the smaller-R collections.  Every output row stores
`fj_jetR`, `run_no`, `lumi_no`, and the 64-bit `event_no`.  `H_ggg` is assigned
only when all three direct gluon daughters are contained within the selected
jet radius; its class index immediately follows `H_gg`.

The CRAB helper can create independent tasks and ROOT outputs for any requested
radius grid in one command.  Task request names and output dataset tags receive
a normalized suffix such as `AKR0p25`:

```bash
cd Ntupler/run
python crab.py \
  --set-input-dataset \
  -p ../test/DeepNtuplizerVR.py \
  --jet-radii 0.2 0.25 0.3 0.4 0.5 0.6 0.7 0.8 0.9 1.0 1.1 1.2 1.3 1.4 1.5 \
  --jet-pt-min 200 \
  --jet-preselection-pt-min 170 \
  --gen-jet-pt-min 100 \
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
