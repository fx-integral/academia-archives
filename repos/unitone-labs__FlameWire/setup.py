# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
# (UnitOne Labs): Alexander
# Copyright © 2026 UnitOne Labs

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import re
import os
import codecs
from os import path
from io import open
from setuptools import setup, find_packages


def read_requirements(path):
    with open(path, "r") as f:
        requirements = f.read().splitlines()
        processed_requirements = []

        for req in requirements:
            if req.startswith("git+") or "@" in req:
                pkg_name = re.search(r"(#egg=)([\w\-_]+)", req)
                if pkg_name:
                    processed_requirements.append(pkg_name.group(2))
                else:
                    continue
            else:
                processed_requirements.append(req)
        return processed_requirements


requirements = read_requirements("requirements.txt")
here = path.abspath(path.dirname(__file__))

with open(path.join(here, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

with codecs.open(os.path.join(here, "flamewire", "__init__.py"), encoding="utf-8") as init_file:
    init_content = init_file.read()
    version_match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", init_content)
    if not version_match:
        raise RuntimeError("Unable to find __version__ in flamewire/__init__.py")
    version_string = version_match.group(1)

setup(
    name="flamewire",  
    version=version_string,
    description="FlameWire is a specialized subnet within the Bittensor network designed to provide decentralized RPC, node, and API services for multiple blockchains.", 
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/unitone-labs/FlameWire",  
    author="flamewire.io",  
    packages=find_packages(),
    include_package_data=True,
    author_email="contact@flamewire.io",  
    license="MIT",
    python_requires=">=3.8",
    install_requires=requirements,
)