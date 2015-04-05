from urllib.request import urlopen
import pkgbuild_lib
import json
import os


PYPI_JSON_URL_FORMAT_TEMPLATE = 'https://pypi.python.org/pypi/{}/json'


def get_checksums(release):
    checksums = {}
    for name in release:
        if name.endswith('_digest'):
            checksum_name = name.rsplit('_', maxsplit=1)[0]
            checksum_name = '{}sums'.format(checksum_name).lower()
            checksums[checksum_name] = release[name]
    return checksums


def update_package_with_pypi(pkgbuild_dir):
    pkgbuild_path = os.path.join(pkgbuild_dir, 'PKGBUILD')
    with open(pkgbuild_path, 'r') as pkgbuild:
        pkgbuild_content = pkgbuild.read()

    pypi_pkgname = pkgbuild_lib.get_pkgbuild_value(pkgbuild_content, '_pypi_pkgname')
    with urlopen(PYPI_JSON_URL_FORMAT_TEMPLATE.format(pypi_pkgname)) as pypi_pkg_fp:
        pypi_pkg_content = pypi_pkg_fp.read().decode('utf-8')
        pypi_pkg = json.loads(pypi_pkg_content)

    new_pkgver = pypi_pkg['info']['version']
    pkgver = pkgbuild_lib.get_pkgbuild_value(pkgbuild_content, 'pkgver')
    vercmp_res = pkgbuild_lib.vercmp(pkgver, new_pkgver)
    if vercmp_res >= 0:
        print('{} already updated'.format(pkgname))
        return

    pkgname = pkgbuild_lib.get_pkgbuild_value(pkgbuild_content, 'pkgname')
    pkgbuild_content = pkgbuild_lib.replace_pkgbuild_var_value(
            pkgbuild_content, 'pkgver', new_pkgver)
    pkgbuild_content = pkgbuild_lib.replace_pkgbuild_var_value(
            pkgbuild_content, 'pkgrel', '1')

    for latest_release in pypi_pkg['releases'][new_pkgver]:
        if latest_release['packagetype'] == 'sdist':
            source_release = latest_release

    checksums = get_checksums(source_release)
    for checksum_name, value in checksums.items():
        try:
            bash_array, array_pattern = pkgbuild_lib.extract_array_var_pattern(
                pkgbuild_content, checksum_name)
            pkgbuild_content = pkgbuild_content.replace(bash_array,
                    array_pattern.format(value))
        except ValueError:
            pass

    with open(pkgbuild_path, 'w') as pkgbuild:
        pkgbuild.write(pkgbuild_content)
    pkgbuild_lib.commit_pkgbuild(
            pkgbuild_dir, pkgname, new_pkgver, [])
