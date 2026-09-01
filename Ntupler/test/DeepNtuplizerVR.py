import FWCore.ParameterSet.Config as cms
import math

from FWCore.ParameterSet.VarParsing import VarParsing


options = VarParsing('analysis')
options.outputFile = 'output.root'
options.maxEvents = -1
options.register('skipEvents', 0, VarParsing.multiplicity.singleton,
                 VarParsing.varType.int, 'skip N events')
options.register('inputDataset', '', VarParsing.multiplicity.singleton,
                 VarParsing.varType.string, 'input dataset (set by CRAB)')
options.register('jetRadius', 0.8, VarParsing.multiplicity.singleton,
                 VarParsing.varType.float,
                 'physical anti-kT jet radius: any positive finite number')
options.register('jetPtMin', 200.0, VarParsing.multiplicity.singleton,
                 VarParsing.varType.float,
                 'minimum raw ungroomed jet pT written to the tuple in GeV')
options.register('jetPreselectionPtMin', 170.0,
                 VarParsing.multiplicity.singleton, VarParsing.varType.float,
                 'minimum raw reco-jet pT used by jetToolbox in GeV')
options.register('genJetPtMin', 100.0, VarParsing.multiplicity.singleton,
                 VarParsing.varType.float,
                 'minimum GenJet and SoftDrop-jet pT in GeV')
options.register('isTrainSample', True, VarParsing.multiplicity.singleton,
                 VarParsing.varType.bool, 'produce a training sample')
options.register('addLowLevel', True, VarParsing.multiplicity.singleton,
                 VarParsing.varType.bool, 'store PF-candidate and secondary-vertex inputs')
options.register('keepAllEvents', False, VarParsing.multiplicity.singleton,
                 VarParsing.varType.bool,
                 'keep all QCD/ttbar events when isTrainSample is false')
options.parseArguments()

if (options.jetRadius <= 0 or math.isnan(options.jetRadius) or
        math.isinf(options.jetRadius)):
    raise ValueError('jetRadius must be a positive finite number')
if min(options.jetPtMin, options.jetPreselectionPtMin,
       options.genJetPtMin) < 0:
    raise ValueError('all jet pT thresholds must be non-negative')
if not options.genJetPtMin <= options.jetPreselectionPtMin <= options.jetPtMin:
    raise ValueError(
        'require genJetPtMin <= jetPreselectionPtMin <= jetPtMin')

jetR = float(options.jetRadius)
jetPtMin = float(options.jetPtMin)
jetPreselectionPtMin = float(options.jetPreselectionPtMin)
genJetPtMin = float(options.genJetPtMin)

# Keep the physical radius independent from CMSSW module names.  The normalized
# token contains only letters and digits, and retains twelve significant digits
# so distinct practical radius values do not silently share a collection name.
radius_token = ('%.12g' % jetR).lower()
radius_token = radius_token.replace('.', 'p').replace('-', 'm').replace('+', '')
radius_token = 'r' + radius_token
jet_collection = 'ak' + radius_token
jet_label = 'AK' + radius_token

print('Running variable-R DNNtuple production with %s (R=%.12g)' %
      (jet_label, jetR))
print('Jet pT thresholds: Gen/SoftDrop=%.1f, reco preselection=%.1f, '
      'tuple=%.1f GeV' %
      (genJetPtMin, jetPreselectionPtMin, jetPtMin))
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
    Cut='pt > %.6g' % jetPreselectionPtMin,
    runOnMC=True,
    addNsub=True,
    maxTau=3,
    addSoftDrop=True,
    addSoftDropSubjets=True,
    subJETCorrPayload='None',
    subJETCorrLevels=['None'],
    bTagDiscriminators=['None'],
    subjetBTagDiscriminators=['None'],
    jetRadius=jetR,
)

# Preserve the staged AK8 thresholds from dev-UL-hww.  The lower producer
# thresholds provide matching headroom below the final tuple selection without
# reconstructing jets outside the generated miniAOD phase space.
getattr(process, jet_collection + 'PFJetsPuppi').jetPtMin = jetPreselectionPtMin
getattr(process, jet_collection + 'PFJetsPuppiSoftDrop').jetPtMin = genJetPtMin
getattr(process, jet_collection + 'GenJetsNoNu').jetPtMin = genJetPtMin
getattr(process, jet_collection + 'GenJetsNoNuSoftDrop').jetPtMin = genJetPtMin

srcJets = cms.InputTag('packedPatJets%sPFPuppiSoftDrop' % jet_label)


from PhysicsTools.PatAlgos.tools.helpers import getPatAlgosToolsTask
patTask = getPatAlgosToolsTask(process)

from RecoJets.JetProducers.ak8GenJets_cfi import ak8GenJets
from RecoJets.Configuration.GenJetParticles_cff import genParticlesForJetsNoNu

process.vrGenJetsWithNu = ak8GenJets.clone(
    src='packedGenParticles',
    rParam=cms.double(jetR),
    jetPtMin=genJetPtMin,
)
process.vrGenJetsWithNuSoftDrop = process.vrGenJetsWithNu.clone(
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
process.deepntuplizer.jetCollectionLabel = cms.untracked.string(jet_label)
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
