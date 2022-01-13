import os
import netplan.libnetplan as libnetplan


def state_from_yaml(confdir, yaml, filename="a.yml"):
    os.makedirs(confdir, exist_ok=True)
    conf = os.path.join(confdir, filename)
    with open(conf, "w+") as f:
        f.write(yaml)
    parser = libnetplan.Parser()
    parser.load_yaml(conf)
    state = libnetplan.State()
    state.import_parser_results(parser)
    return state
