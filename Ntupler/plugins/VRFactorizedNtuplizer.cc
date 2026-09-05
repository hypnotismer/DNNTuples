// Lossless factorization of the existing fillers. No feature recomputation in
// the reader, no quantization, and no change to the per-radius jet selection.
#include <array>
#include <cstring>
#include <map>
#include <memory>
#include <set>
#include "Compression.h"
#include "TNamed.h"
#include "DataFormats/Common/interface/Association.h"
#include "FWCore/Framework/interface/one/EDAnalyzer.h"
#include "FWCore/Framework/interface/MakerMacros.h"
#include "FWCore/ServiceRegistry/interface/Service.h"
#include "CommonTools/UtilAlgos/interface/TFileService.h"
#include "DeepNTuples/Ntupler/interface/JetInfoFiller.h"
#include "DeepNTuples/Ntupler/interface/FatJetInfoFiller.h"
#include "DeepNTuples/Ntupler/interface/PFCompleteFiller.h"
#include "DeepNTuples/Ntupler/interface/SVFiller.h"

using namespace deepntuples;

namespace {
// A complete output value is either jet-dependent or shared. Keep derived
// shared values (including logs) verbatim too, for bitwise legacy equivalence.
int objectGroup(const std::string& name) {
  if (name.find("cpfcandlt_") == 0) return 0;
  if (name.find("npfcand_") == 0) return 1;
  if (name.find("sv_") == 0) return 2;
  return -1;
}
bool sharedArray(const std::string& name) {
  const int group = objectGroup(name);
  if (group < 0) return false;
  const auto suffix = name.substr(name.find('_') + 1);
  static const std::set<std::string> relativePF = {
      "phirel", "etarel", "drminsvin", "dr_uncorrsj1", "dr_uncorrsj2",
      "btagEtaRel", "btagPtRel", "btagPtRatio", "btagPParRatio",
      "btagSip3dVal", "btagSip3dSig", "btagJetDistVal"};
  static const std::set<std::string> relativeSV = {
      "ptrel", "erel", "phirel", "etarel", "deltaR", "ptrel_log", "erel_log"};
  return !(group == 2 ? relativeSV : relativePF).count(suffix);
}
bool eventScalar(const std::string& name) {
  return name == "npv" || name == "rho" || name == "ntrueInt";
}
template<class T> bool declareScalar(AbstractTreeVar* var, TreeData& dst) {
  auto* v = dynamic_cast<TreeVar<T>*>(var);
  if (!v) return false;
  dst.add<T>(var->name, v->get());
  return true;
}
template<class T> bool copyScalar(AbstractTreeVar* var, TreeData& dst) {
  auto* v = dynamic_cast<TreeVar<T>*>(var);
  if (!v) return false;
  dst.fill<T>(var->name, v->get());
  return true;
}
}

class VRFactorizedNtuplizer : public edm::one::EDAnalyzer<edm::one::SharedResources> {
  using Match = edm::Association<reco::GenJetCollection>;
  struct Radius {
    edm::EDGetTokenT<edm::View<pat::Jet>> jets;
    std::array<edm::EDGetTokenT<Match>, 4> matches;
    std::vector<std::unique_ptr<NtupleBase>> fillers;
    PFCompleteFiller* pf = nullptr;
    SVFiller* sv = nullptr;
  };
  std::vector<Radius> radii_;
  edm::EDGetTokenT<reco::CandidateView> candidates_;
  TreeData eventData_, jetData_;
  TreeWriter *events_ = nullptr, *jets_ = nullptr; // TFileService owns trees
  unsigned long long eventIndex_ = 0;
  unsigned long long sourceFileId_ = 0;
  std::string productionConfig_;
  std::array<std::map<reco::CandidatePtr, unsigned>, 2> candidateMaps_;
  std::map<unsigned, unsigned> svMap_;
  const std::array<std::string, 3> indexNames_{{"cpf_indices", "npf_indices", "sv_indices"}};

public:
  explicit VRFactorizedNtuplizer(const edm::ParameterSet& config) {
    usesResource(TFileService::kSharedResource);
    candidates_ = consumes<reco::CandidateView>(config.getParameter<edm::InputTag>("pfcands"));
    sourceFileId_ = config.getParameter<unsigned long long>("sourceFileId");
    const auto configs = config.getParameter<std::vector<edm::ParameterSet>>("collections");
    productionConfig_ = config.getParameter<std::string>("productionConfig");
    if (configs.empty()) throw cms::Exception("VRslim") << "No radii configured";
    const std::array<std::string, 4> matchNames{{"genJetsWithNuMatch",
        "genJetsWithNuSoftDropMatch", "genJetsNoNuMatch", "genJetsNoNuSoftDropMatch"}};
    for (const auto& cfg : configs) {
      if (!cfg.getUntrackedParameter<bool>("addLowLevel", true))
        throw cms::Exception("VRslim") << "addLowLevel must be enabled";
      Radius radius;
      radius.jets = consumes<edm::View<pat::Jet>>(cfg.getParameter<edm::InputTag>("jets"));
      for (unsigned i = 0; i < 4; ++i)
        radius.matches[i] = consumes<Match>(cfg.getParameter<edm::InputTag>(matchNames[i]));
      const double r = cfg.getParameter<double>("jetR");
      radiiValues_.push_back(r);
      radius.fillers.emplace_back(new JetInfoFiller("", r));
      radius.fillers.emplace_back(new FatJetInfoFiller("", r));
      radius.pf = new PFCompleteFiller("", r);
      radius.sv = new SVFiller("", r);
      radius.fillers.emplace_back(radius.pf);
      radius.fillers.emplace_back(radius.sv);
      for (auto& filler : radius.fillers) {
        filler->readConfig(cfg, consumesCollector());
        filler->initData();
      }
      radii_.push_back(std::move(radius));
    }
  }

  void beginJob() override {
    edm::Service<TFileService> fs;
    if (!fs) throw cms::Exception("VRslim") << "TFileService is required";
    fs->file().SetCompressionAlgorithm(ROOT::kLZ4);
    fs->file().SetCompressionLevel(4);
    events_ = new TreeWriter(fs->make<TTree>("Events", "Shared event objects"), "Events");
    jets_ = new TreeWriter(fs->make<TTree>("Jets", "All selected radii"), "Jets");
    fs->make<TNamed>("VRslimSchema", "2");
    fs->make<TNamed>("VRslimConfig", productionConfig_.c_str());
    for (const auto& filler : radii_.front().fillers) {
      for (const auto& entry : filler->treeData().variables()) {
        auto* var = entry.second;
        if (dynamic_cast<TreeMultiVar<float>*>(var)) {
          (sharedArray(entry.first) ? eventData_ : jetData_).addMulti<float>(entry.first);
        } else {
          TreeData& dst = eventScalar(entry.first) ? eventData_ : jetData_;
          if (!(declareScalar<float>(var, dst) || declareScalar<int>(var, dst) ||
                declareScalar<unsigned>(var, dst) || declareScalar<unsigned long long>(var, dst)))
            throw cms::Exception("VRslim") << "Unsupported branch type: " << entry.first;
        }
      }
    }
    eventData_.add<unsigned>("run_no", 0);
    eventData_.add<unsigned>("lumi_no", 0);
    eventData_.add<unsigned long long>("event_no", 0);
    eventData_.add<unsigned long long>("source_file_id", sourceFileId_);
    for (const auto& name : indexNames_) jetData_.addMulti<unsigned>(name);
    jetData_.add<unsigned long long>("event_idx", 0);
    jetData_.add<unsigned>("radius_idx", 0);
    // Record physical R as double too; fj_jetR keeps its legacy float value.
    jetData_.add<double>("jet_radius", 0);
    eventData_.book(events_);
    jetData_.book(jets_);
    // Bounded ROOT baskets: do not allocate 1 MB times every branch/radius.
    events_->getTree()->SetBasketSize("*", 32768);
    jets_->getTree()->SetBasketSize("*", 32768);
    events_->getTree()->SetAutoFlush(-8 * 1024 * 1024);
    jets_->getTree()->SetAutoFlush(-8 * 1024 * 1024);
  }

  void analyze(const edm::Event& event, const edm::EventSetup& setup) override {
    edm::Handle<reco::CandidateView> candidates;
    event.getByToken(candidates_, candidates);
    eventData_.reset();
    eventData_.fill<unsigned>("run_no", event.id().run());
    eventData_.fill<unsigned>("lumi_no", event.id().luminosityBlock());
    eventData_.fill<unsigned long long>("event_no", event.id().event());
    eventData_.fill<unsigned long long>("source_file_id", sourceFileId_);
    for (auto& m : candidateMaps_) m.clear();
    svMap_.clear();
    bool selected = false;
    for (unsigned ir = 0; ir < radii_.size(); ++ir) {
      auto& radius = radii_[ir];
      for (auto& filler : radius.fillers) filler->readEvent(event, setup);
      edm::Handle<edm::View<pat::Jet>> collection;
      event.getByToken(radius.jets, collection);
      std::array<edm::Handle<Match>, 4> matches;
      for (unsigned i = 0; i < 4; ++i) event.getByToken(radius.matches[i], matches[i]);
      for (unsigned ij = 0; ij < collection->size(); ++ij) {
        const auto& jet = collection->at(ij);
        JetHelper helper(&jet, candidates);
        helper.setGenjetWithNu((*matches[0])[collection->refAt(ij)]);
        helper.setGenjetWithNuSoftDrop((*matches[1])[collection->refAt(ij)]);
        helper.setGenjetNoNu((*matches[2])[collection->refAt(ij)]);
        helper.setGenjetNoNuSoftDrop((*matches[3])[collection->refAt(ij)]);
        const auto raw = JetHelper::rawJet(jet);
        bool keep = true;
        for (auto& filler : radius.fillers) {
          if (!filler->fillBranches(raw, ij, helper)) { keep = false; break; }
        }
        if (!keep) continue;
        selected = true;
        jetData_.reset();
        jetData_.fill<unsigned long long>("event_idx", eventIndex_);
        jetData_.fill<unsigned>("radius_idx", ir);
        jetData_.fill<double>("jet_radius", radiiValues_.at(ir));
        std::array<std::vector<unsigned>, 3> indices;
        const std::array<const std::vector<reco::CandidatePtr>*, 2> pointers{{
            &radius.pf->chargedPointers(), &radius.pf->neutralPointers()}};
        for (unsigned g = 0; g < 2; ++g) {
          for (const auto& ptr : *pointers[g]) {
            const unsigned next = candidateMaps_[g].size();
            indices[g].push_back(candidateMaps_[g].emplace(ptr, next).first->second);
          }
        }
        for (auto source : radius.sv->sourceIndices()) {
          const unsigned next = svMap_.size();
          indices[2].push_back(svMap_.emplace(source, next).first->second);
        }
        for (unsigned g = 0; g < 3; ++g) jetData_.setMulti<unsigned>(indexNames_[g], indices[g]);
        for (const auto& filler : radius.fillers) {
          for (const auto& entry : filler->treeData().variables()) {
            auto* var = entry.second;
            if (auto* array = dynamic_cast<TreeMultiVar<float>*>(var)) {
              const auto& values = array->get();
              if (!sharedArray(entry.first)) {
                jetData_.setMulti<float>(entry.first, values);
                continue;
              }
              const auto& ids = indices[objectGroup(entry.first)];
              if (ids.size() != values.size())
                throw cms::Exception("VRslim") << "Object/feature length mismatch: " << entry.first;
              for (unsigned i = 0; i < ids.size(); ++i) {
                const auto& stored = eventData_.getMulti<float>(entry.first);
                if (ids[i] == stored.size()) eventData_.fillMulti<float>(entry.first, values[i]);
                else if (ids[i] > stored.size() || std::memcmp(&stored[ids[i]], &values[i], sizeof(float)))
                  throw cms::Exception("VRslim") << "Shared feature changed between jets: " << entry.first;
              }
            } else {
              TreeData& dst = eventScalar(entry.first) ? eventData_ : jetData_;
              if (!(copyScalar<float>(var, dst) || copyScalar<int>(var, dst) ||
                    copyScalar<unsigned>(var, dst) || copyScalar<unsigned long long>(var, dst)))
                throw cms::Exception("VRslim") << "Unsupported branch: " << entry.first;
            }
          }
        }
        jets_->fill();
      }
    }
    if (selected) { events_->fill(); ++eventIndex_; }
  }

private:
  std::vector<double> radiiValues_;
};

DEFINE_FWK_MODULE(VRFactorizedNtuplizer);
