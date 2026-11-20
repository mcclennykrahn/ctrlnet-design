"""Reordered best-base field choice, provenance and restart/reopen in Chromium."""
import os
from pathlib import Path
import test_allocator_equivalent_bases_e2e as scenario

if __name__ == '__main__':
    scenario.ARTIFACTS = Path(os.environ.get('SCENARIO_ARTIFACTS',
        '/workspace/ctrlnet-v08/cn_post_v08_order_equivalent_bases'))
    scenario.main(reorder_bases=True)
