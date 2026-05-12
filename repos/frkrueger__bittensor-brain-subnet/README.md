# Bittensor Brain Subnet

A Bittensor subnet focused on validating prediction market results. This subnet leverages open-source verification methods to determine the truth value of statements with confidence intervals.

## Overview

The Brain subnet is designed to create a decentralized prediction market verification system where:

- **Miners** verify statements by determining if they are true or false with confidence intervals
- **Validators** evaluate miners' verification results for accuracy and proper methodology

This creates an incentive mechanism where the most accurate and reliable verification miners receive a greater share of TAO emissions.

## Architecture

The subnet consists of the following components:

### Core Components

- **Protocol**: Defines the communication protocol between miners and validators
- **Miners**: Verify statements using open-source methods and provide results
- **Validators**: Evaluate miner results and distribute rewards based on accuracy

### Key Features

- Statement verification with confidence intervals
- Evidence-based verification methodology
- Cross-validation to prevent cheating
- Reward mechanism based on accuracy and evidence quality

## Installation

### Prerequisites

- Python 3.8+
- Bittensor

### Install from Source

```bash
# Clone the repository
git clone https://github.com/yourusername/bittensor-brain-subnet.git
cd bittensor-brain-subnet

# Install the package
pip install -e .
```

## Usage

### Running a Miner

To run a miner on the Brain subnet:

```bash
# Run a miner with default settings
brain-miner --netuid 1 --wallet.name miner --wallet.hotkey default

# Run with custom settings
brain-miner --netuid 1 --wallet.name miner --wallet.hotkey default --miner.verify_timeout 120
```

### Running a Validator

To run a validator on the Brain subnet:

```bash
# Run a validator with default settings
brain-validator --netuid 1 --wallet.name validator --wallet.hotkey default

# Run with custom settings
brain-validator --netuid 1 --wallet.name validator --wallet.hotkey default --validator.run_validation
```

## How It Works

### Verification Process

1. Validators select statements from a database to be verified
2. Miners receive statements and perform verification using:
   - Web searches
   - Database lookups
   - Logical reasoning
   - Evidence collection
3. Miners return results with:
   - True/False determination
   - Confidence score (0.0-1.0)
   - Supporting evidence
   - Explanation of reasoning
   - Methodology description
4. Validators evaluate results based on:
   - Accuracy (compared to ground truth when available)
   - Evidence quality
   - Explanation quality
   - Methodology soundness
5. Validators distribute rewards to miners based on performance

### Validation Process

To prevent cheating, validators may also request miners to validate other miners' results:

1. Validators send a miner's verification result to other miners
2. These miners evaluate if the verification was performed correctly
3. If issues are detected, they provide an alternative result
4. This cross-validation helps ensure integrity in the network

## Development

### Project Structure

```
bittensor-brain-subnet/
├── brain/                  # Core subnet functionality
│   ├── __init__.py         # Package initialization
│   ├── protocol.py         # Communication protocol definitions
│   ├── forward.py          # Forward pass implementation
│   └── reward.py           # Reward mechanism implementation
├── neurons/                # Neuron implementations
│   ├── miner.py            # Miner implementation
│   └── validator.py        # Validator implementation
├── docs/                   # Documentation
├── setup.py                # Package setup
└── README.md               # Project documentation
```

### Customizing the Miner

To create a custom miner with specialized verification methods:

1. Inherit from the base `BrainMiner` class
2. Override the `perform_verification` method with your custom logic
3. Implement specialized search and analysis methods

Example:

```python
from neurons.miner import BrainMiner

class CustomBrainMiner(BrainMiner):
    def perform_verification(self, statement):
        # Your custom verification logic here
        # ...
        return is_true, confidence, evidence, explanation
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.
