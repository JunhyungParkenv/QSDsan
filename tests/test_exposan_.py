#!/usr/bin/env python3
# -*- coding: utf-8 -*-

'''
QSDsan: Quantitative Sustainable Design for sanitation and resource recovery systems

This module is developed by:
    Yalin Li <zoe.yalin.li@gmail.com>

This module is under the University of Illinois/NCSA Open Source License.
Please refer to https://github.com/QSD-Group/QSDsan/blob/main/LICENSE.txt
for license details.
'''

# Just making sure the systems can run is sufficient
__all__ = ('test_exposan',)

def test_exposan():
    from exposan.bsm1 import bsm1
    bsm1.reset_cache()
    bsm1.simulate(t_span=(0,10), method='BDF')

    from exposan import bwaise as bw
    bw.print_summaries((bw.sysA, bw.sysB, bw.sysC))


if __name__ == '__main__':
    test_exposan()