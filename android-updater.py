#!/usr/bin/env python3
import itertools
import os
import re
import subprocess
import sys
import urllib, urllib.error, urllib.request
import xml.etree.ElementTree as etree


def namespace_format(namespace, tag):
    return '{{{namespace}}}{tag}'.format(namespace=namespace, tag=tag)

def open_url_using_url_pattern(url_pattern, num_max=None, delim='-'):
    if num_max is not None:
        for i in range(num_max, 0, -1):
            url_to_be_open = url_pattern.format(delim=delim, num=i)
            try:
                return urllib.request.urlopen(url_to_be_open)
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise e
    return urllib.request.urlopen(url_pattern.format(delim='', num=''))

def get_addon_urls(num_max=3):
    android_addons_list_xml_url_pattern = (
            'https://dl-ssl.google.com/android/repository/addons_list{delim}{num}.xml')
    addons_list_file_obj = open_url_using_url_pattern(android_addons_list_xml_url_pattern,
        num_max=num_max)
    root = etree.parse(addons_list_file_obj).getroot()
    namespace = re.match(r'\{([^}]+)}', root.tag).group(1)

    urls = {}
    for node in root:
        url_node = node.find(namespace_format(namespace, 'url'))
        name_node = node.find(namespace_format(namespace, 'name'))
        url = urllib.parse.urljoin(
                'http://dl-ssl.google.com/android/repository/', url_node.text)
        urls.setdefault(name_node.text, []).append(url)
    return urls

def get_key_for_node(node):
    namespace, tag = re.match(r'\{([^}]+)}(.+)', node.tag).groups()
    if tag == 'system-image':
        abi = node.find(namespace_format(namespace, 'abi')).text
        key = '-'.join([abi, tag])
    elif tag == 'add-on':
        key = node.find(namespace_format(namespace, 'name-id')).text
    else:
        key = tag
    return key.replace('_', '-')

def get_packages(package_list_url_file_objs):
    packages = {}
    for package_list_url_file_obj in package_list_url_file_objs:
        root = etree.parse(package_list_url_file_obj).getroot()
        namespace = re.match(r'\{([^}]+)}', root.tag).group(1)
        for node in root:
            key = get_key_for_node(node)
            packages.setdefault(key, set()).add(node)
    return packages

def open_repository_xml_url(num_max=12):
    android_repository_xml_url_pattern = (
            'https://dl-ssl.google.com/android/repository/repository{delim}{num}.xml')
    return open_url_using_url_pattern(
            android_repository_xml_url_pattern, num_max=num_max)

def get_checksum(archive_node):
    namespace = re.match(r'\{([^}]+)}', archive_node.tag).group(1)
    checksum_node = archive_node.find(namespace_format(namespace, 'checksum'))
    algo_name = checksum_node.attrib['type']
    res = checksum_node.text.strip()
    return algo_name, res

def get_api_level(package_node):
    namespace = re.match(r'\{([^}]+)}', package_node.tag).group(1)
    return package_node.find(namespace_format(namespace, 'api-level')).text

def get_revision(package_node):
    namespace = re.match(r'\{([^}]+)}', package_node.tag).group(1)
    return package_node.find(namespace_format(namespace, 'revision')).text

def get_version(package_node):
    namespace = re.match(r'\{([^}]+)}', package_node.tag).group(1)
    return package_node.find(namespace_format(namespace, 'version')).text

def get_major_minor_micro_revision(package_node):
    namespace = re.match(r'\{([^}]+)}', package_node.tag).group(1)
    revision_node = package_node.find(namespace_format(namespace, 'revision'))
    major = revision_node.find(namespace_format(namespace, 'major')).text
    minor = revision_node.find(namespace_format(namespace, 'minor')).text
    micro = revision_node.find(namespace_format(namespace, 'micro')).text
    return (major, minor, micro)

def get_sort_key_using_version_and_revision(package_node):
    try:
        api_level = int(get_api_level(package_node))
        revision = int(get_revision(package_node))
        return (api_level, revision)
    except AttributeError:
        try:
            return tuple(int(i) for i in
                    get_major_minor_micro_revision(package_node))
        except AttributeError:
            revision = int(get_revision(package_node))
            return (revision,)

def get_latest(package_nodes):
    latest_package_nodes = {}
    for key, values in package_nodes.items():
        latest_package_nodes[key] = list(sorted(values,
            key=get_sort_key_using_version_and_revision,
            reverse=True))[0]
    return latest_package_nodes

def to_aur_package_name(name):
    if name == 'armeabi-v7a-system-image':
        name = 'armv7a-eabi-system-image'
    return '-'.join(['android', name])

def update_pkgbuild(src_path, package_node):
    namespace = re.match(r'\{([^}]+)}', package_node.tag).group(1)
    pkgbuild_path = os.path.join(src_path, 'PKGBUILD')
    try:
        api_level = get_api_level(package_node)
        rev = 'r{:0>2}'.format(int(get_revision(package_node).strip()))
        pkgver = '{}_{}'.format(api_level, rev)
    except AttributeError:
        rev = '{}.{}.{}'.format(
                *get_major_minor_micro_revision(package_node))
        pkgver = rev

    archives = package_node.find(namespace_format(namespace, 'archives'))
    for archive in archives:
        if archive.attrib.get('os', 'any') in ('any', 'linux'):
            break
    else:
        return

    checksum_algo_name, checksum_algo_res = get_checksum(archive)
    with open(pkgbuild_path, 'r') as pkgbuild:
        pkgbuild_content = pkgbuild.read()
        pkgbuild_content = re.sub(r'(?<=_rev\=)[^\n]+', rev,
                pkgbuild_content, flags=re.MULTILINE)
        pkgbuild_content = re.sub(r'(?<=_apilevel\=)[^\n]+', api_level,
                pkgbuild_content, flags=re.MULTILINE)
        pkgbuild_content = re.sub(r'(?<=pkgrel\=)[^\n]+', '1',
                pkgbuild_content, flags=re.MULTILINE)
        pkgbuild_content = re.sub(r'(?<={}sums\=\(\')[^\']+'.format(checksum_algo_name),
                checksum_algo_res, pkgbuild_content, flags=re.MULTILINE)

        pkgname = re.search(r'(?<=pkgname\=)[^\s#]+', pkgbuild_content).group()
    with open(pkgbuild_path, 'w') as pkgbuild:
        pkgbuild.write(pkgbuild_content)

    cwd = os.getcwd()
    os.chdir(src_path)
    try:
        subprocess.check_call(['git', 'commit', 'PKGBUILD', '-m',
            '[{pkgname}] Update pkg ({pkgver})'.format(pkgname=pkgname, pkgver=pkgver)])
    except subprocess.CalledProcessError:
        pass
    finally:
        os.chdir(cwd)

def main():
    directory = sys.argv[1]
    package_list_open_urls = [urllib.request.urlopen(i)
            for i in itertools.chain.from_iterable(get_addon_urls().values())]
    package_list_open_urls.append(open_repository_xml_url())
    all_nodes = get_packages(package_list_open_urls)
    del all_nodes['license']
    del all_nodes['extra']
    latest_package_nodes = get_latest(all_nodes)
    for i in latest_package_nodes:
        try:
            src_path = os.path.join(directory,
                    to_aur_package_name(i))
            update_pkgbuild(src_path, latest_package_nodes[i])
        except FileNotFoundError:
            pass

if __name__ == '__main__':
    main()
