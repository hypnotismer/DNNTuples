"""Multi-R PUPPI reconstruction with lossless Events/Jets output (CMSSW 10_6)."""
import FWCore.ParameterSet.Config as cms
import json
from FWCore.ParameterSet.VarParsing import VarParsing
from DeepNTuples.Ntupler.vrslim_config import parse_radii, radius_label, validate_thresholds

options = VarParsing('analysis')
options.outputFile = 'output.root'
options.maxEvents = -1
for name, default, kind, description in [
    ('jetRadii', ','.join(str(i / 10.) for i in range(1, 16)), 'string', 'Comma-separated physical R values'),
    ('inputDataset', '', 'string', 'Dataset description for era and truth flags'),
    ('era', 'auto', 'string', 'auto, UL17 or UL18; auto infers from dataset and input names'),
    ('skipEvents', 0, 'int', 'Number of input events to skip'),
    ('jetPtMin', 200., 'float', 'Final raw jet pT threshold'),
    ('jetPreselectionPtMin', 170., 'float', 'Reco producer/selector pT threshold'),
    ('genJetPtMin', 100., 'float', 'Gen and SoftDrop producer pT threshold'),
    ('isTrainSample', True, 'bool', 'Use training truth selection'),
    ('keepAllEvents', False, 'bool', 'Disable QCD/ttbar inference subsampling'),
    ('writeReference', False, 'bool', 'Also write ordinary per-radius tuples for a SMALL validation pilot'),
]:
    options.register(name, default, VarParsing.multiplicity.singleton,
                     getattr(VarParsing.varType, kind), description)
options.parseArguments()
radii = parse_radii(options.jetRadii)
validate_thresholds(options.genJetPtMin, options.jetPreselectionPtMin, options.jetPtMin)
description = ' '.join([options.inputDataset] + list(options.inputFiles))
era = options.era
if era == 'auto':
    era = 'UL17' if ('UL17' in description or '2017/' in description) else (
        'UL18' if ('UL18' in description or '2018/' in description) else 'auto')
tags = {'auto': 'auto:phase1_2018_realistic', 'UL17': '106X_mc2017_realistic_v9',
        'UL18': '106X_upgrade2018_realistic_v16_L1v1'}
if era not in tags:
    raise ValueError('Unsupported era: ' + era)

process = cms.Process('DNNFiller')
process.load('FWCore.MessageService.MessageLogger_cfi')
process.MessageLogger.cerr.FwkReport.reportEvery = 1000
process.options = cms.untracked.PSet(allowUnscheduled=cms.untracked.bool(True),
                                    wantSummary=cms.untracked.bool(True))
process.maxEvents = cms.untracked.PSet(input=cms.untracked.int32(options.maxEvents))
process.source = cms.Source('PoolSource', fileNames=cms.untracked.vstring(options.inputFiles),
                            skipEvents=cms.untracked.uint32(options.skipEvents))
process.TFileService = cms.Service('TFileService', fileName=cms.string(options.outputFile))
for module in ['Configuration.StandardSequences.Services_cff',
               'Configuration.StandardSequences.GeometryRecoDB_cff',
               'Configuration.StandardSequences.MagneticField_cff',
               'Configuration.StandardSequences.FrontierConditions_GlobalTag_cff',
               'TrackingTools.TransientTrack.TransientTrackBuilder_cfi']:
    process.load(module)
from Configuration.AlCa.GlobalTag import GlobalTag
process.GlobalTag = GlobalTag(process.GlobalTag, tags[era], '')

from PhysicsTools.PatAlgos.tools.helpers import getPatAlgosToolsTask
from DeepNTuples.Ntupler.jetToolbox_cff import jetToolbox
from DeepNTuples.Ntupler.DeepNtuplizer_cfi import deepntuplizer
from RecoJets.JetProducers.ak8GenJets_cfi import ak8GenJets
from RecoJets.Configuration.GenJetParticles_cff import genParticlesForJetsNoNu

# One shared PUPPI product for ALL R. clonePackedCands preserves original keys,
# used by the legacy JetHelper to recover unweighted packedPFCandidates.
process.load('CommonTools.PileupAlgos.Puppi_cff')
process.puppi.candName = cms.InputTag('packedPFCandidates')
process.puppi.vertexName = cms.InputTag('offlineSlimmedPrimaryVertices')
process.puppi.clonePackedCands = cms.bool(True)
task = getPatAlgosToolsTask(process)
task.add(process.puppi)
process.vrSlimGenParticlesNoNu = genParticlesForJetsNoNu.clone(src='packedGenParticles')
task.add(process.vrSlimGenParticlesNoNu)
collections = []
references = cms.Sequence()
for r in radii:
    token = radius_label(r)
    collection, label = 'ak' + token, 'AK' + token
    jetToolbox(process, collection, 'seq' + label, 'noOutput',
               PUMethod='Puppi', puppiCollection='puppi',
               JETCorrPayload='None', JETCorrLevels=['None'],
               Cut='pt > %.6g' % options.jetPreselectionPtMin, runOnMC=True,
               addNsub=True, maxTau=3, addSoftDrop=True, addSoftDropSubjets=True,
               subJETCorrPayload='None', subJETCorrLevels=['None'],
               bTagDiscriminators=['None'], subjetBTagDiscriminators=['None'], jetRadius=r)
    for suffix, threshold in [('PFJetsPuppi', options.jetPreselectionPtMin),
                              ('PFJetsPuppiSoftDrop', options.genJetPtMin),
                              ('GenJetsNoNu', options.genJetPtMin),
                              ('GenJetsNoNuSoftDrop', options.genJetPtMin)]:
        getattr(process, collection + suffix).jetPtMin = threshold
    src = cms.InputTag('packedPatJets%sPFPuppiSoftDrop' % label)
    cfg = deepntuplizer.clone(jets=src, useReclusteredJets=True, jetR=r, jetType='AK',
                             jetCollectionLabel=cms.untracked.string(label),
                             jetPtMin=options.jetPtMin, jetPtMax=-1., jetAbsEtaMax=-1.,
                             addLowLevel=True, bDiscriminators=cms.vstring(),
                             isTrainSample=options.isTrainSample, keepAllEvents=options.keepAllEvents)
    lower = description.lower()
    cfg.isQCDSample = 'qcd' in lower
    cfg.isTTBarSample = 'tott' in lower or 'ttbar' in lower
    cfg.isHVV2DVarMassSample = '2dmesh' in lower
    cfg.isPythia = 'pythia' in lower
    cfg.isHerwig = 'herwig' in lower
    cfg.isMadGraph = 'madgraph' in lower
    for variant in ['WithNu', 'WithNuSoftDrop', 'NoNu', 'NoNuSoftDrop']:
        name = 'vrSlim' + label + 'GenJets' + variant
        producer = ak8GenJets.clone(src='vrSlimGenParticlesNoNu' if 'NoNu' in variant else 'packedGenParticles',
                                   rParam=cms.double(r), jetPtMin=options.genJetPtMin)
        if variant.endswith('SoftDrop'):
            producer.useSoftDrop = cms.bool(True)
            producer.zcut = cms.double(0.1)
            producer.beta = cms.double(0.)
            producer.R0 = cms.double(r)
            producer.useExplicitGhosts = cms.bool(True)
        setattr(process, name, producer)
        task.add(getattr(process, name))
        matcher = cms.EDProducer('GenJetMatcher', src=src, matched=cms.InputTag(name),
                                 mcPdgId=cms.vint32(), mcStatus=cms.vint32(),
                                 checkCharge=cms.bool(False), maxDeltaR=cms.double(r),
                                 resolveAmbiguities=cms.bool(True), resolveByMatchQuality=cms.bool(False))
        setattr(process, name + 'Match', matcher)
        task.add(getattr(process, name + 'Match'))
        setattr(cfg, 'genJets' + variant + 'Match', cms.InputTag(name + 'Match'))
    collections.append(cms.PSet(**cfg.parameters_()))
    if options.writeReference:
        setattr(process, 'reference' + label, cfg)
        references += getattr(process, 'reference' + label)

process.vrslim = cms.EDAnalyzer('VRFactorizedNtuplizer',
                               pfcands=cms.InputTag('packedPFCandidates'),
                               productionConfig=cms.string(json.dumps({
                                   'schema': 1, 'radii': radii, 'globalTag': tags[era],
                                   'thresholds': [options.genJetPtMin, options.jetPreselectionPtMin, options.jetPtMin],
                                   'isTrainSample': options.isTrainSample, 'keepAllEvents': options.keepAllEvents,
                                   'collections': [c.dumpPython() for c in collections],
                               }, sort_keys=True)),
                               collections=cms.VPSet(*collections))
process.p = cms.Path(process.vrslim + references)
process.p.associate(task)
print('VRslim radii:', radii, 'era:', era, 'writeReference:', options.writeReference)
