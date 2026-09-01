import FWCore.ParameterSet.Config as cms

from FWCore.ParameterSet.VarParsing import VarParsing


options = VarParsing('analysis')
options.outputFile = 'output.root'
options.maxEvents = -1
options.register('skipEvents', 0, VarParsing.multiplicity.singleton,
                 VarParsing.varType.int, 'skip N events')
options.register('inputDataset', '', VarParsing.multiplicity.singleton,
                 VarParsing.varType.string, 'input dataset (set by CRAB)')
options.register('jetRadius', 8, VarParsing.multiplicity.singleton,
                 VarParsing.varType.int,
                 'jet radius in tenths: an integer from 2 (R=0.2) to 15 (R=1.5)')
options.register('jetPtMin', 20.0, VarParsing.multiplicity.singleton,
                 VarParsing.varType.float,
                 'minimum raw ungroomed jet pT in GeV')
options.register('isTrainSample', True, VarParsing.multiplicity.singleton,
                 VarParsing.varType.bool, 'produce a training sample')
options.register('addLowLevel', True, VarParsing.multiplicity.singleton,
                 VarParsing.varType.bool, 'store PF-candidate and secondary-vertex inputs')
options.register('keepAllEvents', False, VarParsing.multiplicity.singleton,
                 VarParsing.varType.bool,
                 'keep all QCD/ttbar events when isTrainSample is false')
options.parseArguments()

if options.jetRadius < 2 or options.jetRadius > 15:
    raise ValueError('jetRadius must be an integer from 2 to 15')
if options.jetPtMin < 0:
    raise ValueError('jetPtMin must be non-negative')

jet_radius_index = int(options.jetRadius)
jetR = jet_radius_index / 10.0
jetPtMin = float(options.jetPtMin)
jet_collection = 'ak%d' % jet_radius_index
jet_label = 'AK%d' % jet_radius_index

print('Running variable-R DNNtuple production with %s (R=%.1f)' %
      (jet_label, jetR))
print('Input files:', options.inputFiles)

globalTagMap = {
    'auto': 'auto:phase1_2018_realistic',
    'UL18': '106X_upgrade2018_realistic_v16_L1v1',
    'UL17': '106X_mc2017_realistic_v9',
}

sample_description = ' '.join([options.inputDataset] + list(options.inputFiles))
era = 'auto'
if 'UL17' in sample_description or '2017/' in sample_description:
    era = 'UL17'
elif 'UL18' in sample_description or '2018/' in sample_description:
    era = 'UL18'
print('Era:', era)


process = cms.Process('DNNFiller')

process.load('FWCore.MessageService.MessageLogger_cfi')
process.MessageLogger.cerr.FwkReport.reportEvery = 1000
process.options = cms.untracked.PSet(
    allowUnscheduled=cms.untracked.bool(True),
    wantSummary=cms.untracked.bool(False),
)

process.TFileService = cms.Service(
    'TFileService', fileName=cms.string(options.outputFile))
process.maxEvents = cms.untracked.PSet(
    input=cms.untracked.int32(options.maxEvents))
process.source = cms.Source(
    'PoolSource',
    fileNames=cms.untracked.vstring(options.inputFiles),
    skipEvents=cms.untracked.uint32(options.skipEvents),
)

process.load('Configuration.EventContent.EventContent_cff')
process.load('Configuration.StandardSequences.Services_cff')
process.load('Configuration.StandardSequences.GeometryRecoDB_cff')
process.load('Configuration.StandardSequences.MagneticField_cff')
process.load('Configuration.StandardSequences.FrontierConditions_GlobalTag_cff')
process.load('TrackingTools.TransientTrack.TransientTrackBuilder_cfi')
from Configuration.AlCa.GlobalTag import GlobalTag
process.GlobalTag = GlobalTag(process.GlobalTag, globalTagMap[era], '')
print('Global tag:', process.GlobalTag.globaltag)


# Recluster raw PUPPI jets.  No JEC payload or correction level is applied.
from DeepNTuples.Ntupler.jetToolbox_cff import jetToolbox
jetToolbox(
    process,
    jet_collection,
    'dummySeq',
    'noOutput',
    PUMethod='Puppi',
    JETCorrPayload='None',
    JETCorrLevels=['None'],
    Cut='pt > %.6g' % jetPtMin,
    runOnMC=True,
    addNsub=True,
    maxTau=3,
    addSoftDrop=True,
    addSoftDropSubjets=True,
    subJETCorrPayload='None',
    subJETCorrLevels=['None'],
    bTagDiscriminators=['None'],
    subjetBTagDiscriminators=['None'],
)

# Apply the threshold only to raw ungroomed reco jets.  GenJet targets and
# groomed jets remain uncut to avoid threshold-induced matching inefficiency.
getattr(process, jet_collection + 'PFJetsPuppi').jetPtMin = jetPtMin
getattr(process, jet_collection + 'PFJetsPuppiSoftDrop').jetPtMin = 0.0
getattr(process, jet_collection + 'GenJetsNoNu').jetPtMin = 0.0
getattr(process, jet_collection + 'GenJetsNoNuSoftDrop').jetPtMin = 0.0

srcJets = cms.InputTag('packedPatJets%sPFPuppiSoftDrop' % jet_label)


from PhysicsTools.PatAlgos.tools.helpers import getPatAlgosToolsTask
patTask = getPatAlgosToolsTask(process)

from RecoJets.JetProducers.ak8GenJets_cfi import ak8GenJets
from RecoJets.Configuration.GenJetParticles_cff import genParticlesForJetsNoNu

process.vrGenJetsWithNu = ak8GenJets.clone(
    src='packedGenParticles',
    rParam=cms.double(jetR),
    jetPtMin=0.0,
)
process.vrGenJetsWithNuSoftDrop = process.vrGenJetsWithNu.clone(
    jetPtMin=0.0,
    useSoftDrop=cms.bool(True),
    zcut=cms.double(0.1),
    beta=cms.double(0.0),
    R0=cms.double(jetR),
    useExplicitGhosts=cms.bool(True),
)
process.packedGenParticlesForVRJetsNoNu = genParticlesForJetsNoNu.clone(
    src='packedGenParticles')
process.vrGenJetsNoNu = process.vrGenJetsWithNu.clone(
    src='packedGenParticlesForVRJetsNoNu')
process.vrGenJetsNoNuSoftDrop = process.vrGenJetsWithNuSoftDrop.clone(
    src='packedGenParticlesForVRJetsNoNu')

process.vrGenJetsWithNuMatch = cms.EDProducer(
    'GenJetMatcher',
    src=srcJets,
    matched=cms.InputTag('vrGenJetsWithNu'),
    mcPdgId=cms.vint32(),
    mcStatus=cms.vint32(),
    checkCharge=cms.bool(False),
    maxDeltaR=cms.double(jetR),
    resolveAmbiguities=cms.bool(True),
    resolveByMatchQuality=cms.bool(False),
)
process.vrGenJetsWithNuSoftDropMatch = process.vrGenJetsWithNuMatch.clone(
    matched=cms.InputTag('vrGenJetsWithNuSoftDrop'))
process.vrGenJetsNoNuMatch = process.vrGenJetsWithNuMatch.clone(
    matched=cms.InputTag('vrGenJetsNoNu'))
process.vrGenJetsNoNuSoftDropMatch = process.vrGenJetsWithNuMatch.clone(
    matched=cms.InputTag('vrGenJetsNoNuSoftDrop'))

process.genJetTask = cms.Task(
    process.vrGenJetsWithNu,
    process.vrGenJetsWithNuSoftDrop,
    process.packedGenParticlesForVRJetsNoNu,
    process.vrGenJetsNoNu,
    process.vrGenJetsNoNuSoftDrop,
    process.vrGenJetsWithNuMatch,
    process.vrGenJetsWithNuSoftDropMatch,
    process.vrGenJetsNoNuMatch,
    process.vrGenJetsNoNuSoftDropMatch,
)


process.load('DeepNTuples.Ntupler.DeepNtuplizer_cfi')
process.deepntuplizer.jets = srcJets
process.deepntuplizer.useReclusteredJets = True
process.deepntuplizer.jetR = jetR
process.deepntuplizer.jetType = 'AK'
process.deepntuplizer.jetPtMin = jetPtMin
process.deepntuplizer.jetPtMax = -1
process.deepntuplizer.jetAbsEtaMax = -1
process.deepntuplizer.addLowLevel = options.addLowLevel
process.deepntuplizer.bDiscriminators = cms.vstring()
process.deepntuplizer.genJetsWithNuMatch = 'vrGenJetsWithNuMatch'
process.deepntuplizer.genJetsWithNuSoftDropMatch = 'vrGenJetsWithNuSoftDropMatch'
process.deepntuplizer.genJetsNoNuMatch = 'vrGenJetsNoNuMatch'
process.deepntuplizer.genJetsNoNuSoftDropMatch = 'vrGenJetsNoNuSoftDropMatch'

sample_name_lower = sample_description.lower()
process.deepntuplizer.isQCDSample = 'qcd' in sample_name_lower
process.deepntuplizer.isTTBarSample = (
    'tott' in sample_name_lower or 'ttbar' in sample_name_lower)
process.deepntuplizer.isHVV2DVarMassSample = '2dmesh' in sample_name_lower
process.deepntuplizer.isPythia = 'pythia' in sample_name_lower
process.deepntuplizer.isHerwig = 'herwig' in sample_name_lower
process.deepntuplizer.isMadGraph = 'madgraph' in sample_name_lower
process.deepntuplizer.isTrainSample = options.isTrainSample
process.deepntuplizer.keepAllEvents = options.keepAllEvents

process.p = cms.Path(process.deepntuplizer)
process.p.associate(patTask)
process.p.associate(process.genJetTask)
