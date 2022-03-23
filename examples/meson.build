#https://mesonbuild.com/FAQ.html#but-i-really-want-to-use-wildcards
c = run_command(find, '-name', '*.yaml', check: true)
examples = c.stdout().strip().split('\n')
install_data(
    examples,
    install_dir: join_paths(get_option('datadir'), 'doc', 'netplan', 'examples'))
