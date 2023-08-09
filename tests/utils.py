import os
import netplan


def state_from_yaml(confdir, yaml, filename="a.yml"):
    os.makedirs(confdir, exist_ok=True)
    conf = os.path.join(confdir, filename)
    with open(conf, "w+") as f:
        f.write(yaml)
    parser = netplan.Parser()
    parser.load_yaml(conf)
    state = netplan.State()
    state.import_parser_results(parser)
    return state
