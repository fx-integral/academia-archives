# SPDX-FileCopyrightText: 2025 Rayleigh Research <to@rayleigh.re>
# SPDX-License-Identifier: MIT
from contextlib import contextmanager
from pathlib import Path
import os
import subprocess

import pytest

#-------------------------------------------------------------------------

BASE_DIR = Path(__file__).parents[2].resolve()
BIN_PATH = BASE_DIR / "build/src/cpp/taosim"
DOC_DIR = BASE_DIR / "run"

@contextmanager
def chdir(path: Path):
    origin = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(origin)

#-------------------------------------------------------------------------

@pytest.mark.parametrize("simulation_descriptor_filename", [
    ("PrintingAgentExample.xml"),
    ("SellerBuyerExample.xml"),
    ("SimulationExample.xml")
])
def test_simulator_heuristic(simulation_descriptor_filename: str) -> None:
    ref_output_file = Path(__file__).parent / "testdata" / f"{Path(simulation_descriptor_filename).stem}RefOutput.txt"
    ref_output = ref_output_file.read_text()
    with chdir(DOC_DIR):
        simulator_process = subprocess.Popen(
            [BIN_PATH, "-f", simulation_descriptor_filename],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
    output, _ = simulator_process.communicate()
    assert output == ref_output

#-------------------------------------------------------------------------
