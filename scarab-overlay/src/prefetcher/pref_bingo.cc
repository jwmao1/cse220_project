/*
 * Bingo Spatial Data Prefetcher for Scarab.
 *
 * Adapted from the HPCA 2019 reference implementation:
 * https://github.com/bakhshalipour/Bingo
 */

#include "prefetcher/pref_bingo.h"

#include "globals/assert.h"
#include "globals/global_types.h"
#include "globals/global_vars.h"

#include "memory/memory.param.h"
#include "prefetcher/pref.param.h"
#include "prefetcher/pref_bingo.param.h"
#include "prefetcher/pref_common.h"

#include "statistics.h"

#include <algorithm>
#include <cstdint>
#include <memory>
#include <unordered_map>
#include <utility>
#include <vector>

namespace {

enum class Event {
  PC_ADDRESS,
  PC_OFFSET,
};

struct FilterData {
  Addr pc = 0;
  uns offset = 0;
};

struct AccumulationData {
  Addr pc = 0;
  uns offset = 0;
  std::vector<bool> pattern;
};

template <typename T>
class FullyAssociativeTable {
 public:
  struct Entry {
    Flag valid = FALSE;
    Addr key = 0;
    Counter last_access = 0;
    T data;
  };

  explicit FullyAssociativeTable(uns size) : entries_(size) {}

  Entry* find(Addr key) {
    auto it = lookup_.find(key);
    if (it == lookup_.end())
      return nullptr;
    Entry& entry = entries_[it->second];
    ASSERT(0, entry.valid && entry.key == key);
    entry.last_access = ++timestamp_;
    return &entry;
  }

  Entry erase(Addr key) {
    auto it = lookup_.find(key);
    if (it == lookup_.end())
      return {};
    Entry old_entry = entries_[it->second];
    entries_[it->second] = {};
    lookup_.erase(it);
    return old_entry;
  }

  Entry insert(Addr key, const T& data) {
    auto it = lookup_.find(key);
    if (it != lookup_.end()) {
      Entry old_entry = entries_[it->second];
      entries_[it->second].data = data;
      entries_[it->second].last_access = ++timestamp_;
      return old_entry;
    }

    uns victim = 0;
    for (uns ii = 0; ii < entries_.size(); ++ii) {
      if (!entries_[ii].valid) {
        victim = ii;
        break;
      }
      if (entries_[ii].last_access < entries_[victim].last_access)
        victim = ii;
    }

    Entry old_entry = entries_[victim];
    if (old_entry.valid)
      lookup_.erase(old_entry.key);
    entries_[victim] = {TRUE, key, ++timestamp_, data};
    lookup_[key] = victim;
    return old_entry;
  }

 private:
  std::vector<Entry> entries_;
  std::unordered_map<Addr, uns> lookup_;
  Counter timestamp_ = 0;
};

class PatternHistoryTable {
 public:
  PatternHistoryTable(uns size, uns assoc, uns pattern_len, uns min_addr_width, uns max_addr_width, uns pc_width,
                      float vote_threshold)
      : assoc_(assoc),
        pattern_len_(pattern_len),
        min_addr_width_(min_addr_width),
        max_addr_width_(max_addr_width),
        pc_width_(pc_width),
        vote_threshold_(vote_threshold),
        entries_(size) {
    ASSERTM(0, size && assoc && size % assoc == 0, "Bingo PHT size must be a non-zero multiple of associativity\n");
    num_sets_ = size / assoc;
    ASSERTM(0, is_power_of_two(num_sets_), "Bingo PHT set count must be a power of two\n");
    index_len_ = log2_power_of_two(num_sets_);
    ASSERTM(0, index_len_, "Bingo PHT must contain at least two sets\n");
    ASSERTM(0, pc_width_ + min_addr_width_ > index_len_,
            "Bingo PC+offset event must contain more bits than the PHT index\n");
    ASSERTM(0, pc_width_ + max_addr_width_ > index_len_,
            "Bingo PC+address event must contain more bits than the PHT index\n");
  }

  void insert(Addr pc, Addr block_number, std::vector<bool> pattern) {
    const uns offset = block_number % pattern_len_;
    pattern = rotate(pattern, -static_cast<int>(offset));
    const Addr key = build_key(pc, block_number);
    const uns set = key % num_sets_;
    const Addr tag = key / num_sets_;

    Entry* victim = &entries_[set * assoc_];
    for (uns way = 0; way < assoc_; ++way) {
      Entry& entry = entries_[set * assoc_ + way];
      if (entry.valid && entry.tag == tag) {
        victim = &entry;
        break;
      }
      if (!entry.valid || (victim->valid && entry.last_access < victim->last_access))
        victim = &entry;
    }

    *victim = {TRUE, key, tag, ++timestamp_, std::move(pattern)};
  }

  std::pair<Event, std::vector<bool>> find(Addr pc, Addr block_number) {
    const Addr key = build_key(pc, block_number);
    const uns set = key % num_sets_;
    const Addr tag = key / num_sets_;
    const Addr min_tag_mask = bit_mask(pc_width_ + min_addr_width_ - index_len_);
    const Addr max_tag_mask = bit_mask(pc_width_ + max_addr_width_ - index_len_);
    std::vector<std::vector<bool>> min_matches;

    for (uns way = 0; way < assoc_; ++way) {
      Entry& entry = entries_[set * assoc_ + way];
      if (!entry.valid)
        continue;
      if ((entry.tag & max_tag_mask) == (tag & max_tag_mask)) {
        entry.last_access = ++timestamp_;
        return {Event::PC_ADDRESS, rotate(entry.pattern, block_number % pattern_len_)};
      }
      if ((entry.tag & min_tag_mask) == (tag & min_tag_mask))
        min_matches.push_back(entry.pattern);
    }

    return {Event::PC_OFFSET, rotate(vote(min_matches), block_number % pattern_len_)};
  }

 private:
  struct Entry {
    Flag valid = FALSE;
    Addr key = 0;
    Addr tag = 0;
    Counter last_access = 0;
    std::vector<bool> pattern;
  };

  static Flag is_power_of_two(uns value) {
    return value && !(value & (value - 1));
  }

  static uns log2_power_of_two(uns value) {
    uns result = 0;
    while (value > 1) {
      value >>= 1;
      ++result;
    }
    return result;
  }

  static Addr bit_mask(uns width) {
    return width >= 64 ? static_cast<Addr>(-1) : (static_cast<Addr>(1) << width) - 1;
  }

  static std::vector<bool> rotate(const std::vector<bool>& pattern, int amount) {
    if (pattern.empty())
      return {};
    const int len = pattern.size();
    amount %= len;
    std::vector<bool> rotated(len);
    for (int ii = 0; ii < len; ++ii)
      rotated[ii] = pattern[(ii - amount + len) % len];
    return rotated;
  }

  Addr build_key(Addr pc, Addr block_number) const {
    pc &= bit_mask(pc_width_);
    block_number &= bit_mask(max_addr_width_);
    const Addr offset = block_number & bit_mask(min_addr_width_);
    const Addr base = block_number >> min_addr_width_;
    Addr key = (base << (pc_width_ + min_addr_width_)) | (pc << min_addr_width_) | offset;
    Addr folded_tag = (pc << min_addr_width_) | offset;
    do {
      folded_tag >>= index_len_;
      key ^= folded_tag & bit_mask(index_len_);
    } while (folded_tag);
    return key;
  }

  std::vector<bool> vote(const std::vector<std::vector<bool>>& patterns) const {
    if (patterns.empty())
      return {};
    std::vector<bool> result(pattern_len_, false);
    for (uns offset = 0; offset < pattern_len_; ++offset) {
      uns count = 0;
      for (const auto& pattern : patterns) {
        ASSERT(0, pattern.size() == pattern_len_);
        count += pattern[offset];
      }
      result[offset] = static_cast<float>(count) / patterns.size() >= vote_threshold_;
    }
    return result;
  }

  uns assoc_;
  uns num_sets_ = 0;
  uns index_len_ = 0;
  uns pattern_len_;
  uns min_addr_width_;
  uns max_addr_width_;
  uns pc_width_;
  float vote_threshold_;
  std::vector<Entry> entries_;
  Counter timestamp_ = 0;
};

class Bingo {
 public:
  Bingo(HWP_Info* hwp_info, uns pattern_len)
      : hwp_info_(hwp_info),
        pattern_len_(pattern_len),
        filter_table_(PREF_BINGO_FILTER_TABLE_SIZE),
        accumulation_table_(PREF_BINGO_ACCUMULATION_TABLE_SIZE),
        pht_(PREF_BINGO_PHT_SIZE, PREF_BINGO_PHT_ASSOC, pattern_len, PREF_BINGO_MIN_ADDR_WIDTH,
             PREF_BINGO_MAX_ADDR_WIDTH, PREF_BINGO_PC_WIDTH, PREF_BINGO_VOTE_THRESHOLD) {}

  void access(uns8 proc_id, Addr line_addr, Addr load_pc, uns32 global_hist) {
    if (!load_pc)
      return;

    const Addr block_number = line_addr >> LOG2(L1_LINE_SIZE);
    const Addr region_number = block_number / pattern_len_;
    const uns region_offset = block_number % pattern_len_;
    auto* accumulation_entry = accumulation_table_.find(region_number);
    if (accumulation_entry) {
      accumulation_entry->data.pattern[region_offset] = true;
      return;
    }

    auto* filter_entry = filter_table_.find(region_number);
    if (!filter_entry) {
      STAT_EVENT(proc_id, BINGO_TRIGGER);
      filter_table_.insert(region_number, {load_pc, region_offset});
      issue_prefetches(proc_id, block_number, load_pc, global_hist);
      return;
    }

    if (filter_entry->data.offset == region_offset)
      return;

    AccumulationData data = {filter_entry->data.pc, filter_entry->data.offset, std::vector<bool>(pattern_len_, false)};
    data.pattern[filter_entry->data.offset] = true;
    data.pattern[region_offset] = true;
    filter_table_.erase(region_number);
    auto victim = accumulation_table_.insert(region_number, data);
    if (victim.valid)
      insert_in_pht(victim.key, victim.data);
  }

  void eviction(uns8 proc_id, Addr line_addr) {
    const Addr block_number = line_addr >> LOG2(L1_LINE_SIZE);
    const Addr region_number = block_number / pattern_len_;
    filter_table_.erase(region_number);
    auto entry = accumulation_table_.erase(region_number);
    if (!entry.valid)
      return;
    STAT_EVENT(proc_id, BINGO_REGION_END);
    insert_in_pht(entry.key, entry.data);
  }

 private:
  void insert_in_pht(Addr region_number, const AccumulationData& data) {
    const Addr trigger_block = region_number * pattern_len_ + data.offset;
    pht_.insert(data.pc, trigger_block, data.pattern);
  }

  void issue_prefetches(uns8 proc_id, Addr block_number, Addr load_pc, uns32 global_hist) {
    auto prediction = pht_.find(load_pc, block_number);
    if (prediction.second.empty()) {
      STAT_EVENT(proc_id, BINGO_PHT_MISS);
      return;
    }

    STAT_EVENT(proc_id, prediction.first == Event::PC_ADDRESS ? BINGO_PHT_PC_ADDRESS_HIT : BINGO_PHT_PC_OFFSET_HIT);
    const Addr region_base = block_number / pattern_len_ * pattern_len_;
    for (uns offset = 0; offset < prediction.second.size(); ++offset) {
      if (!prediction.second[offset])
        continue;
      const Addr pref_block = region_base + offset;
      if (pref_block == block_number)
        continue;
      STAT_EVENT(proc_id, BINGO_PREF_REQUESTED);
      if (pref_addto_ul1req_queue_set(proc_id, pref_block, hwp_info_->id, 0, load_pc, global_hist, FALSE))
        STAT_EVENT(proc_id, BINGO_PREF_QUEUED);
      else
        STAT_EVENT(proc_id, BINGO_PREF_QUEUE_REJECTED);
    }
  }

  HWP_Info* hwp_info_;
  uns pattern_len_;
  FullyAssociativeTable<FilterData> filter_table_;
  FullyAssociativeTable<AccumulationData> accumulation_table_;
  PatternHistoryTable pht_;
};

std::vector<std::unique_ptr<Bingo>> bingo_prefetchers;

Flag is_power_of_two(uns value) {
  return value && !(value & (value - 1));
}

}  // namespace

extern "C" void pref_bingo_init(HWP* hwp) {
  if (!PREF_BINGO_ON)
    return;

  ASSERTM(0, PREF_UL1_ON, "Bingo requires --pref_ul1_on 1\n");
  ASSERTM(0, PREF_BINGO_REGION_SIZE && PREF_BINGO_REGION_SIZE % L1_LINE_SIZE == 0,
          "Bingo region size must be a non-zero multiple of the L1 line size\n");
  ASSERTM(0, is_power_of_two(PREF_BINGO_REGION_SIZE / L1_LINE_SIZE),
          "Bingo blocks per region must be a power of two\n");
  ASSERTM(0, PREF_BINGO_FILTER_TABLE_SIZE && PREF_BINGO_ACCUMULATION_TABLE_SIZE,
          "Bingo filter and accumulation tables must not be empty\n");
  ASSERTM(0, PREF_BINGO_VOTE_THRESHOLD >= 0.0 && PREF_BINGO_VOTE_THRESHOLD <= 1.0,
          "Bingo vote threshold must be between zero and one\n");

  hwp->hwp_info->enabled = TRUE;
  const uns pattern_len = PREF_BINGO_REGION_SIZE / L1_LINE_SIZE;
  bingo_prefetchers.reserve(NUM_CORES);
  for (uns proc_id = 0; proc_id < NUM_CORES; ++proc_id)
    bingo_prefetchers.emplace_back(std::make_unique<Bingo>(hwp->hwp_info, pattern_len));
}

extern "C" void pref_bingo_ul1_access(uns8 proc_id, Addr line_addr, Addr load_pc, uns32 global_hist) {
  ASSERT(proc_id, proc_id < bingo_prefetchers.size());
  bingo_prefetchers[proc_id]->access(proc_id, line_addr, load_pc, global_hist);
}

extern "C" void pref_bingo_ul1_evict(uns8 proc_id, Addr line_addr) {
  ASSERT(proc_id, proc_id < bingo_prefetchers.size());
  bingo_prefetchers[proc_id]->eviction(proc_id, line_addr);
}
