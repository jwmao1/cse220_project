#ifndef __PREF_BINGO_H__
#define __PREF_BINGO_H__

#include "pref_common.h"

#ifdef __cplusplus
extern "C" {
#endif

void pref_bingo_init(HWP* hwp);
void pref_bingo_ul1_access(uns8 proc_id, Addr line_addr, Addr load_pc, uns32 global_hist);
void pref_bingo_ul1_evict(uns8 proc_id, Addr line_addr);

#ifdef __cplusplus
}
#endif

#endif
