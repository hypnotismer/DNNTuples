# dev-UL-VRslim

Lossless multi-R training storage based on dev-UL-VR. All active legacy filler
branches are preserved. No half precision, quantization, feature removal, or
Python recomputation of physics variables is used. ROOT compression remains
LZ4 level 4. The C++ writer evaluates the original fillers, writes invariant
object values once, and stores jet-dependent values per association.

## Production in CMSSW

Use the same CMSSW environment and build procedure as dev-UL-VR, but select
branch `dev-UL-VRslim`. In the CMSSW package directory:

```bash
scram b -j4
cmsRun Ntupler/test/DeepNtuplizerVRslim.py \
  inputFiles=file:mini.root era=UL17 \
  jetRadii=0.1,0.2,0.25,0.4,0.8,1.5 maxEvents=1000
```

Default radii: 0.1, 0.2, ..., 1.5. Any list of positive finite physical radii is
supported; duplicate radii and collisions in normalized CMSSW labels are
rejected. Explicitly set `era=UL17` for private files with generic names.
`inputDataset` supplies the existing sample flags if filenames do not identify
QCD, ttbar, 2dmesh, Pythia, Herwig or MadGraph. Input lists in one production
group must have compatible sample flags and era.

There is one PUPPI producer per process. Each configured R has its own reco
jets, SoftDrop/subjets, tau1–3, truth matching and gen jets with/without neutrinos
and grooming. No JEC is applied. Existing thresholds stay at Gen/SoftDrop
100 GeV, reco preselection 170 GeV, final raw jet pT 200 GeV. Other existing
truth/selection logic, including the ggg label, is inherited from the fillers.
No fixed jet-count cap or additional per-candidate truncation is introduced.
All R are static CMSSW modules, executed for every event, not randomly routed.

## ROOT layout (schema 1)

The ROOT contains `vrslim/Events` and `vrslim/Jets` TTrees. Events with no selected
jets at any R are omitted. Each retained event is one Events entry. Jets are
written in event order, then configured radius order, then original jet order.

Events stores `run_no/lumi_no/event_no`, `npv/rho/ntrueInt`, and all invariant
`cpfcandlt_*`, `npfcand_*`, `sv_*` arrays. Arrays contain only the union of objects
used by selected jets. Charged PF and lost tracks share the charged table, but
deduplication uses the full EDM pointer (ProductID and key). SVs use the index
in the event's single input SV collection. IDs are local to an event. PUPPI
clones must retain the original packed-candidate key ordering, as required by
the inherited JetHelper; the reference pilot below must be run on production
MiniAODs before large-scale use.

Jets stores:

- All original jet scalars: p4, label, targets, truth observers, counts, etc.
- `event_idx` (uint64): entry in this file's Events TTree.
- `radius_idx` (uint32): index in the configured R list.
- `jet_radius` (double): exact configured physical R. Original `fj_jetR` remains
  float32 for compatibility.
- `cpf_indices`, `npf_indices`, `sv_indices` (uint32 arrays): local indices into
  the corresponding Events object tables, preserving the original filler order.
  `cpf_indices` includes lost tracks in the same order as the legacy filler.
- Original particle/SV arrays whose values depend on the jet, aligned with
  the relevant index array.

The per-association PF arrays are `phirel`, `etarel`, `drminsvin`,
`dr_uncorrsj1`, `dr_uncorrsj2`, and the seven active charged `btag*` arrays.
SV association arrays are `ptrel`, `erel`, `phirel`, `etarel`, `deltaR`,
`ptrel_log`, `erel_log`. All are stored at the original float32 precision.
Even derived invariant arrays such as logs and type indicators are stored
verbatim once. This avoids round-off changes from reconstructing them later.
Every repeated shared value is compared bitwise by the writer; a disagreement
aborts production rather than silently replacing a value.

`vrslim/VRslimSchema` records version 1 and `vrslim/VRslimConfig` records radii,
thresholds, global tag, sample flags and per-radius filler configuration.

Two inherited indexing defects are fixed in this branch: the nested-subjet
path now uses the leaf candidate key, and lost-track detection uses the full
candidate pointer rather than a colliding PF/lost-track integer key. These
fixes also apply to reference tuples made from this branch. Differences from
older tuples in affected events are bug fixes, not numerical compression.

## Read as jet-based training samples

Outside CMSSW, install the Python 3 dependencies in an isolated environment:

```bash
python3 -m pip install -r Ntupler/scripts/requirements-vrslim.txt
```

```python
import sys
sys.path.insert(0, 'Ntupler/scripts')
from vrslim_io import iter_jets

for batch in iter_jets('output.root', step_size=1024, include_internal=True):
    # batch is {legacy_branch_name: awkward.Array}, one row per jet.
    # Use batch['jet_radius'] as the model's R input.
    # Feed legacy fields through the existing sorting/padding/normalization.
    pass
```

Each batch reads the referenced event range and gathers the object arrays with
the stored indices. Jet-dependent arrays are read directly. Repeated feature
arrays only exist temporarily in RAM; they are not written to disk. A trainer
that expects one ordinary ROOT TTree needs its input-reading hook changed to
call this iterator; merely pointing its current YAML at Jets will not work.
The actual model/training repository is outside this package and is not
modified here. Keep the existing label mapping synchronized with the ggg label
in dev-UL-VR; an older AK8 YAML may contain hard-coded obsolete label offsets.

All jets/radii of the same source event must go to the same train/validation/test
split. Independent generated samples may reuse run/lumi/event; include source
dataset/file provenance when assigning splits. Do not treat equal numeric IDs
in separate MiniAODs as a reason to deduplicate their events. File-local
event_idx is a storage coordinate, not a globally unique event identifier.

## Existing 100-input Condor job pattern

The existing file-list row (100 comma-separated MiniAODs) can be retained.
Initialize CMSSW as before, then replace the old per-file loop and `hadd` with:

```bash
python3 Ntupler/scripts/run_vrslim.py \
  --input-files "$INPUTFILES" --output dnntuple.root \
  era=UL17 jetRadii=0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0,1.1,1.2,1.3,1.4,1.5
```

Use a Python 3 environment with the dependencies above while keeping `cmsRun`
from the initialized CMSSW environment on PATH. The driver runs each MiniAOD
separately, retries up to five times, validates each result, and finally rebases
event_idx while merging. It publishes the final file only after validation.
Temporary per-input ROOTs are cleaned up; input MiniAODs are never modified.
On terminal failure it preserves the failed cmsRun log beside the requested
output. The `.inputs.json` manifest must be transferred alongside the ROOT.
The new entry point always enables low-level output; omit the old
`addLowLevel=1` command-line argument when adapting an existing JDL.
The driver uses local paths for final output; keep the existing external
transfer step after it succeeds. Existing files are not overwritten.

To merge already-produced files separately:

```bash
python3 Ntupler/scripts/vrslim_io.py merge merged.root raw0.root raw1.root
python3 Ntupler/scripts/vrslim_io.py validate merged.root
```

Do not use ordinary `hadd`: it concatenates Events without updating Jets.event_idx.
Merge refuses differing reconstruction configurations, invalid indices, or
inconsistent feature lengths. Candidate indices remain unchanged because they
are event-local. The merge reads bounded chunks and preserves all feature bits.
Plan temporary disk space for both the per-input outputs and the merged output
(roughly twice the job's final size). A 100-input job is not mandatory: tune
inputs/job using a multi-R pilot's CPU, peak memory and disk measurements.
Multi-R clustering is still additional CPU work even though storage is shared.

## Required server pilot before full production

```bash
cmsRun Ntupler/test/DeepNtuplizerVRslim.py \
  inputFiles=file:mini.root era=UL17 jetRadii=0.2,0.25,0.8,1.5 \
  maxEvents=1000 writeReference=True
python3 Ntupler/scripts/vrslim_io.py compare output.root
```

`writeReference=True` also writes full legacy jet TTrees under
`referenceAKr0p2/tree`, etc., from the exact same jet products. The comparison
checks every legacy branch, dtype, jagged length, order and floating-point bit.
Use representative QCD and signals (including ggg, heavy flavour/lost tracks,
small/large R, empty subjets). Disable references for production: they duplicate
the data intentionally and defeat the storage saving.

Compare a small R=0.8 run to DeepNtuplizerVR.py too, to validate the shared-PUPPI
configuration against the previous separate job. Run the pilot on at least two
MiniAOD files and validate their merged output. Measure compressed bytes/event,
not branch count, before extrapolating the full sample size. There is no
guaranteed TB size without that measurement.

Local I/O tests:

```bash
python3 -m pytest -q Ntupler/test/test_vrslim_io.py
```

These synthetic tests validate ROOT I/O and merging but do not replace compiling
and running the CMSSW producer with real MiniAOD inputs.
