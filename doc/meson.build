if pandoc.found()
    custom_target(
        input: ['manpage-header.md', 'structure-id.md', 'netplan-yaml.md', 'manpage-footer.md'],
        output: 'netplan.5',
        command: [pandoc, '-s', '-o', '@OUTPUT@', '--from=markdown-smart', '@INPUT@'],
        install: true,
        install_dir: join_paths(get_option('mandir'), 'man5'))
    custom_target(
        input: 'netplan-yaml.md',
        output: 'netplan.html',
        command: [pandoc, '-s', '--metadata', 'title="Netplan reference"', '--toc', '-o', '@OUTPUT@', '@INPUT@'],
        install: true,
        install_dir: join_paths(get_option('datadir'), 'doc', 'netplan'))
    foreach doc : ['netplan-apply', 'netplan-dbus', 'netplan-generate', 'netplan-get', 'netplan-set', 'netplan-try', 'netplan-validate']
        markdown = files(doc + '.md')
        manpage = doc + '.8'
        custom_target(
            input: markdown,
            output: manpage,
            command: [pandoc, '-s', '-o', '@OUTPUT@', '--shift-heading-level-by=-1', '--from=markdown-smart', '@INPUT@'],
            install: true,
            install_dir: join_paths(get_option('mandir'), 'man8'))
    endforeach
else
    warning('Program "pandoc" not found!  Cannot generate documentation/man pages')
endif
