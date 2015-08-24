from urllib.request import urlopen
import os
import pkgbuild_lib
import re
import urllib.parse


def get_version(dsc_content):
    return re.search(r'{}\s+([^\s]+)'.format('Version:'),
        dsc_content).group(1)

def get_checksums(dsc_content, package_source_name):
    checksums = {}
    field_name_pattern = r'{}([^:]+):'.format(re.escape('Checksums-'))
    for match in re.finditer(field_name_pattern , dsc_content):
        start_pos = match.span()[1]
        checksum_name = match.group(1)
        pat = re.compile(r'([^\s]+)\s+([^\s]+)\s+{}'.format(
            re.escape(package_source_name)))
        checksums[checksum_name] = pat.search(dsc_content, start_pos).group(1)
    return checksums

def get_dsc_url_from_debian_package_page(package_name):
    debian_package_page = 'https://packages.debian.org/sid/{}'.format(
            package_name)
    with urlopen(debian_package_page) as page:
        page_content = page.read().decode('utf-8')
        res = re.search('http((?:(?!\.dsc).)+)\.dsc', page_content)
        url_dsc = res.group()
    return url_dsc

def update_package_with_dsc(run, pkgbuild_dir, dsc_url, package_source_name_pattern):
    with urlopen(dsc_url) as dsc:
        dsc_content = dsc.read().decode('utf-8')
    version = re.search(r'{}\s+([^\s]+)'.format('Version:'),
        dsc_content).group(1)
    new_pkgver = version.rsplit('-', 1)[0]

    pkgbuild_path = os.path.join(pkgbuild_dir, 'PKGBUILD')
    with open(pkgbuild_path, 'r') as pkgbuild:
        pkgbuild_content = pkgbuild.read()

    pkgname = pkgbuild_lib.get_pkgbuild_value(pkgbuild_content, 'pkgname')
    pkgver = pkgbuild_lib.get_pkgbuild_value(pkgbuild_content, 'pkgver')
    vercmp_res = pkgbuild_lib.vercmp(run, pkgver, new_pkgver)
    if vercmp_res >= 0:
        print('{} already updated'.format(pkgname))
        return

    pkgbuild_content = pkgbuild_lib.replace_pkgbuild_var_value(
            pkgbuild_content, 'pkgver', new_pkgver)
    pkgbuild_content = pkgbuild_lib.replace_pkgbuild_var_value(
            pkgbuild_content, 'pkgrel', '1')

    package_source_name = package_source_name_pattern.format(new_pkgver)
    checksums = get_checksums(dsc_content, package_source_name)
    for checksum_name, value in checksums.items():
        try:
            bash_array, array_pattern = pkgbuild_lib.extract_array_var_pattern(
                pkgbuild_content, '{}sums'.format(checksum_name.lower()))
            pkgbuild_content = pkgbuild_content.replace(bash_array,
                    array_pattern.format(value))
        except (ValueError, StopIteration):
            pass

    with open(pkgbuild_path, 'w') as pkgbuild:
        pkgbuild.write(pkgbuild_content)
    pkgbuild_lib.commit_pkgbuild(run, pkgbuild_dir,
            pkgname, new_pkgver, [])
