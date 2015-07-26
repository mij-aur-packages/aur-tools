from invoke import ctask, Collection
from urllib.request import urlopen
import android_repository_lib as android_repo_lib
import dsc_lib
import ftplib
import functools
import itertools
import os
import pkgbuild_lib
import urllib
import pypi_lib


DEFAULT_PKGBUILD_SRC_PARENT_PATH = os.path.join(
        os.path.dirname(__file__), os.path.pardir, 'aur-packages')


def out(ctx):
    def run(*args, **kwargs):
        res = ctx.run(*args, **kwargs)
        return res.stdout
    return run


def get_latest_lubuntu_artwork_dsc(run):
    base_url = 'archive.ubuntu.com'
    directory = 'ubuntu/pool/universe/l/lubuntu-artwork'
    with ftplib.FTP(base_url) as ftp:
        ftp.login()
        ftp.cwd(directory)
        dsc_list = []
        for i in ftp.nlst():
            if i.endswith('.dsc'):
                dsc_list.append(i)

        dsc_list = list(sorted(dsc_list, key=functools.cmp_to_key(
            lambda *args, **kwargs: pkgbuild_lib.vercmp(run, *args,
                **kwargs))))
        dsc_name = dsc_list[-1]
    path_to_dsc = os.path.join(directory, dsc_name)
    url = urllib.parse.urljoin('http://{}'.format(base_url), path_to_dsc)
    return url


@ctask
def update_android_packages(ctx,
        android_pkgbuild_src_parent=DEFAULT_PKGBUILD_SRC_PARENT_PATH,
        exclude_codename=None):

    package_list_open_urls = [urllib.request.urlopen(i)
            for i in itertools.chain.from_iterable(
                android_repo_lib.get_addon_url_paths().values())]
    package_list_open_urls.append(android_repo_lib.get_repository_xml_url())

    android_items = android_repo_lib.get_android_items(package_list_open_urls)
    android_items = [item for item in android_items
            if item.package_type != 'extra' and 'obsolete' not in item]
    items_by_package_name = {}
    for item in android_items:
        android_pkg_name = android_repo_lib.get_android_package_name(item)
        items_by_package_name.setdefault(android_pkg_name, [])
        items_by_package_name[android_pkg_name].append(item)

    latest_packages = {}
    for package_name, items in items_by_package_name.items():
        pkgs = []
        for itm in items:
            try:
                if itm.codename != exclude_codename:
                    pkgs.append(itm)
            except AttributeError:
                pkgs.append(itm)
        pkgs = sorted(pkgs, key=android_repo_lib.get_android_version, reverse=True)
        if pkgs:
            latest_packages[package_name] = pkgs[0]

    for package_name, item in latest_packages.items():
        pkgbuild_src = os.path.join(android_pkgbuild_src_parent,
            android_repo_lib.to_aur_package_name(package_name))
        try:
            android_repo_lib.update_package(out(ctx), pkgbuild_src, item)
        except FileNotFoundError:
            pass


@ctask
def update_packages_that_have_dsc(ctx,
        src_parent=DEFAULT_PKGBUILD_SRC_PARENT_PATH):
    pkgbuild_dirs = []
    for i in ['lubuntu-artwork', 'xapian-omega']:
        pkgbuild_dirs.append(os.path.join(src_parent, i))

    urls = [get_latest_lubuntu_artwork_dsc(out(ctx)),
            dsc_lib.get_dsc_url_from_debian_package_page('xapian-omega')]

    pkg_source_name_patterns = ['lubuntu-artwork_{}.',
            'xapian-omega_{}.orig.tar.xz']

    for src_path, url, pkg_src_name_pattern in zip(
            pkgbuild_dirs, urls, pkg_source_name_patterns):
        dsc_lib.update_package_with_dsc(out(ctx), src_path, url, pkg_src_name_pattern)


@ctask
def update_pypi_packages(ctx,
        src_parent=DEFAULT_PKGBUILD_SRC_PARENT_PATH):
    pkgbuild_dirs = []
    for i in ['pyhamcrest']:
        pkgbuild_dirs.append(os.path.join(src_parent, i))

    for src_path in pkgbuild_dirs:
        pypi_lib.update_package_with_pypi(out(ctx), src_path)


@ctask(pre=[update_android_packages,
    update_packages_that_have_dsc,
    update_pypi_packages])
def update_packages(ctx):
    print("Finish updating packages")

ns = Collection()
ns.add_task(update_android_packages)
ns.add_task(update_packages_that_have_dsc)
ns.add_task(update_pypi_packages)
ns.add_task(update_packages, default=True)
