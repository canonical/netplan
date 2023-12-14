import sys

import datetime

# Custom configuration for the Sphinx documentation builder.
# All configuration specific to your project should be done in this file.
#
# The file is included in the common conf.py configuration file.
# You can modify any of the settings below or add any configuration that
# is not covered by the common conf.py file.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/
#
# If you're not familiar with Sphinx and don't want to use advanced
# features, it is sufficient to update the settings in the "Project
# information" section.

############################################################
# Project information
############################################################

# Product name
project = 'Netplan'
author = 'Netplan team'

# The title you want to display for the documentation in the sidebar.
# You might want to include a version number here.
# To not display any title, set this option to an empty string.
html_title = project + ' documentation'

# The default value uses the current year as the copyright year.
#
# For static works, it is common to provide the year of first publication.
# Another option is to give the first year and the current year
# for documentation that is often changed, e.g. 2022–2023 (note the en-dash).
#
# A way to check a GitHub repo's creation date is to obtain a classic GitHub
# token with 'repo' permissions here: https://github.com/settings/tokens
# Next, use 'curl' and 'jq' to extract the date from the GitHub API's output:
#
# curl -H 'Authorization: token <TOKEN>' \
#   -H 'Accept: application/vnd.github.v3.raw' \
#   https://api.github.com/repos/canonical/<REPO> | jq '.created_at'

copyright = '%s, %s' % (datetime.date.today().year, author)

# Open Graph configuration - defines what is displayed as a link preview
# when linking to the documentation from another website (see https://ogp.me/)
# The URL where the documentation will be hosted (leave empty if you
# don't know yet)
ogp_site_url = 'https://netplan.readthedocs.io/en/stable/netplan-apply/'
# The documentation website name (usually the same as the product name)
ogp_site_name = project
# The URL of an image or logo that is used in the preview
ogp_image = 'https://assets.ubuntu.com/v1/253da317-image-document-ubuntudocs.svg'

# Update with the local path to the favicon for your product
# (default is the circle of friends)
html_favicon = '.sphinx/_static/favicon.png'

# The logo
html_logo = '.sphinx/_static/netplan.svg'

# (Some settings must be part of the html_context dictionary, while others
#  are on root level. Don't move the settings.)
html_context = {

    # Change to the link to the website of your product (without "https://")
    # For example: "ubuntu.com/lxd" or "microcloud.is"
    # If there is no product website, edit the header template to remove the
    # link (see the readme for instructions).
    'product_page': 'netplan.io',

    # Add your product tag (the orange part of your logo, will be used in the
    # header) to ".sphinx/_static" and change the path here (start with "_static")
    # (default is the circle of friends)
    'product_tag': '_static/tag.png',

    # Change to the discourse instance you want to be able to link to
    # using the :discourse: metadata at the top of a file
    # (use an empty value if you don't want to link)
    'discourse': 'https://discourse.ubuntu.com/c/foundations/',

    # Change to the Mattermost channel you want to link to
    # (use an empty value if you don't want to link)
    'mattermost': 'https://chat.canonical.com/canonical/channels/documentation',

    # Change to the GitHub URL for your project
    'github_url': 'https://github.com/canonical/netplan',

    # Change to the branch for this version of the documentation
    'github_version': 'main',

    # Change to the folder that contains the documentation
    # (usually "/" or "/docs/")
    'github_folder': '/doc/',

    # Change to an empty value if your GitHub repo doesn't have issues enabled.
    # This will disable the feedback button and the issue link in the footer.
    'github_issues': 'https://bugs.launchpad.net/netplan/',

    # Controls the existence of Previous / Next buttons at the bottom of pages
    # Valid options: none, prev, next, both
    'sequential_nav': "none"
}

# If your project is on documentation.ubuntu.com, specify the project
# slug (for example, "lxd") here.
slug = ""

############################################################
# Redirects
############################################################

# Set up redirects (https://documatt.gitlab.io/sphinx-reredirects/usage.html)
# For example: 'explanation/old-name.html': '../how-to/prettify.html',

redirects = {
    'README.md': '/',
    'netplan': '/netplan-yaml',
}

############################################################
# Link checker exceptions
############################################################

# Links to ignore when checking links

linkcheck_ignore = [
    'http://127.0.0.1:8000'
]

# Pages on which to ignore anchors
# (This list will be appended to linkcheck_anchors_ignore_for_url)

custom_linkcheck_anchors_ignore_for_url = []

############################################################
# Additions to default configuration
############################################################

# The following settings are appended to the default configuration.
# Use them to extend the default functionality.

# Add extensions
custom_extensions = [
    'breathe',
]

# Add MyST extensions
custom_myst_extensions = ["colon_fence"]

# Add files or directories that should be excluded from processing.
custom_excludes = [
    'doc-cheat-sheet*',
    'manpage-footer.md',
    'manpage-header.md',
    'CODE_OF_CONDUCT.md',
]

# Add CSS files (located in .sphinx/_static/)
custom_html_css_files = []

# Add JavaScript files (located in .sphinx/_static/)
custom_html_js_files = []

# The following settings override the default configuration.

# Specify a reST string that is included at the end of each file.
# If commented out or empty, use the default (which pulls the reuse/links.txt
# file into each reST file).
custom_rst_epilog = ''

# By default, the documentation includes a feedback button at the top.
# You can disable it by setting the following configuration to True.
disable_feedback_button = False

# Add tags that you want to use for conditional inclusion of text
# (https://www.sphinx-doc.org/)
custom_tags = []

############################################################
# Additional configuration
############################################################

# Add any configuration that is not covered by the common conf.py file.

smartquotes_action = 'qe'

# Doxygen
# https://breathe.readthedocs.io/en/latest/directives.html
# breathe_projects = {"Netplan": "../doxyxml/"}
breathe_projects_source = {"auto-apidoc": ("../", [
    "include/netplan.h",
    "include/parse-nm.h",
    "include/parse.h",
    "include/types.h",
    "include/util.h",
    "src/error.c",
    "src/names.c",
    "src/netplan.c",
    "src/parse-nm.c",
    "src/parse.c",
    "src/types.c",
    "src/util.c",
    "src/validation.c",
])}

breathe_doxygen_config_options = {
    'MACRO_EXPANSION': 'YES',
    'EXPAND_ONLY_PREDEF': 'YES',
    'PREDEFINED': 'NETPLAN_PUBLIC NETPLAN_DEPRECATED',
}
breathe_domain_by_extension = {
    "h": "c",
    "c": "c",
}
# breathe_doxygen_aliases =
breathe_default_project = "auto-apidoc"

# Options for MyST
myst_title_to_header = True
suppress_warnings = ['myst.xref_missing']

#
# sys.path.append('./')
#
# from custom_conf import *

# Configuration file for the Sphinx documentation builder.
# You should not do any modifications to this file. Put your custom
# configuration into the custom_conf.py file.
# If you need to change this file, contribute the changes upstream.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/

############################################################
# Extensions
############################################################

extensions = [
    'sphinx_design',
    'sphinx_tabs.tabs',
    'sphinx_reredirects',
    'youtube-links',
    'related-links',
    'custom-rst-roles',
    'terminal-output',
    'sphinx_copybutton',
    'sphinxext.opengraph',
    'myst_parser',
    'sphinxcontrib.jquery',
    'notfound.extension'
]
extensions.extend(custom_extensions)

# Configuration for extensions

# Additional MyST syntax
myst_enable_extensions = [
    'substitution',
    'deflist',
    'linkify'
]
myst_enable_extensions.extend(custom_myst_extensions)

# Used for related links
if 'discourse_prefix' not in html_context and 'discourse' not in html_context:
    html_context['discourse_prefix'] = html_context['discourse'] + '/t/'

# The default for notfound_urls_prefix usually works, but not for
# documentation on documentation.ubuntu.com
if slug:
    notfound_urls_prefix = '/' + slug + '/en/latest/'

notfound_context = {
    'title': 'Page not found',
    'body': '<h1>Page not found</h1>\n\n<p>Sorry, but the documentation page \
        that you are looking for was not found.</p>\n<p>Documentation changes \
        over time, and pages are moved around. We try to redirect you to the \
        updated content where possible, but unfortunately, that didn\'t work \
        this time (maybe because the content you were looking for does not \
        exist in this version of the documentation).</p>\n<p>You can try to use \
        the navigation to locate the content you\'re looking for, or search for \
        a similar page.</p>\n',
}

# Default image for OGP (to prevent font errors, see
# https://github.com/canonical/sphinx-docs-starter-pack/pull/54 )
if 'ogp_image' not in locals():
    ogp_image = 'https://assets.ubuntu.com/v1/253da317-image-document-ubuntudocs.svg'

############################################################
# General configuration
############################################################

exclude_patterns = [
    '_build',
    'Thumbs.db',
    '.DS_Store',
    '.sphinx',
]
exclude_patterns.extend(custom_excludes)

rst_epilog = '''
.. include:: /reuse/links.txt
'''

if 'custom_rst_epilog' in locals() and 'custom_rst_epilog' != '':
    rst_epilog = custom_rst_epilog

source_suffix = {
    '.rst': 'restructuredtext',
    '.md': 'markdown',
}

if 'conf_py_path' not in html_context and 'github_folder' not in html_context:
    html_context['conf_py_path'] = html_context['github_folder']

# For ignoring specific links
linkcheck_anchors_ignore_for_url = [
    r'https://github\.com/.*'
]
linkcheck_anchors_ignore_for_url.extend(custom_linkcheck_anchors_ignore_for_url)

# Tags cannot be added directly in custom_conf.py, so add them here

tags = ()

for tag in custom_tags:
    tags.add(tag)

############################################################
# Styling
############################################################

# Find the current builder
builder = 'dirhtml'
if '-b' in sys.argv:
    builder = sys.argv[sys.argv.index('-b')+1]

# Setting templates_path for epub makes the build fail
if builder == 'dirhtml' or builder == 'html':
    templates_path = ['.sphinx/_templates']

# Theme configuration
html_theme = 'furo'
html_last_updated_fmt = ''
html_permalinks_icon = '¶'

if html_title == '':
    html_theme_options = {
        'sidebar_hide_name': True
        }

############################################################
# Additional files
############################################################

html_static_path = ['.sphinx/_static']

html_css_files = [
    'custom.css',
    'header.css',
    'github_issue_links.css',
    'furo_colors.css'
]
html_css_files.extend(custom_html_css_files)

html_js_files = ['header-nav.js']
if 'github_issues' in html_context and html_context['github_issues'] and not disable_feedback_button:
    html_js_files.append('github_issue_links.js')
html_js_files.extend(custom_html_js_files)
