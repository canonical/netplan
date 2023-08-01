# A simple tool to convert a Network Manager keyfile to Netplan YAML
# How to use:
#   From the Netplan source directory, run:
#     PYTHONPATH=. python3 tools/keyfile_to_yaml.py path/to/the/file.nmconnection

import io
import sys

from netplan_cli import libnetplan

if len(sys.argv) < 2:
    print("Pass the NM keyfile as parameter")
    sys.exit(1)

parser = libnetplan.Parser()
state = libnetplan.State()

try:
    parser.load_keyfile(sys.argv[1])
    state.import_parser_results(parser)
except Exception as e:
    print(e)
    sys.exit(1)

output = io.StringIO()
state.dump_yaml(output)

print(output.getvalue())
