#!/usr/bin/env python3
import collections
import datetime
import hashlib
import io
import itertools
import os
import re
import subprocess
import sys
import urllib, urllib.error, urllib.request
import xml.etree.ElementTree as etree
import xmltodict


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

def open_repository_xml_url(num_max=12):
    android_repository_xml_url_pattern = (
            'https://dl-ssl.google.com/android/repository/repository{delim}{num}.xml')
    return open_url_using_url_pattern(
            android_repository_xml_url_pattern, num_max=num_max)

class AttrDict(collections.OrderedDict):
    __init_marker = '__initializing_super_of_attrdict'
    def __init__(self, *args, **kwargs):
        object.__setattr__(self, self.__init_marker, True)
        super().__init__(*args, **kwargs)
        object.__delattr__(self, self.__init_marker)

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as e:
            raise AttributeError(e)

    def __setattr__(self, name, value):
        if hasattr(self, self.__init_marker):
            super().__setattr__(name, value)
        else:
            self[name] = value

    def __delattr__(self, name):
        del self[name]

def wrap_to_list(obj, expected_types=None):
    if isinstance(obj, list):
        return obj
    elif expected_types is None or isinstance(obj, expected_types):
        return [obj]
    else:
        raise Exception('obj not the expected type. Expected {}; Actual: {}'.format(
            expected_types, type(obj)))

def normalize_xmldict(xmldict):
    conds = (key.startswith('@')
            or key == '#text' for key in xmldict.keys())
    if len(xmldict) > 1 and not all(conds) and any(conds):
        raise Exception('Must not contain both text and subnode')

    attrdict = AttrDict()
    for key, value in xmldict.items():
        name = key.replace('sdk:', '', 1).replace('-', '_')
        if isinstance(value, dict):
            attrdict[name] = normalize_xmldict(value)
        elif isinstance(value, list):
            normalized_nodes = []
            for subnode in value:
                normalized_nodes.append(normalize_xmldict(subnode))
            attrdict[name] = normalized_nodes
        elif isinstance(value, (str, type(None))):
            attrdict[name] = value
            continue
        elif '#text' in xmldict:
            attrdict[name] = xmldict['#text']
            continue
        else:
            raise Exception('Element must be a list or a dict')
    return attrdict

def android_arch(arch):
    if arch == 'armeabi-v7a':
        return 'armv7-eabi'
    return arch


def get_android_package_name(item):
    if item.package_type == 'system_image':
        if item.tag_id == 'default':
            package_name = '_'.join([android_arch(item.abi), item.package_type])
        else:
            package_name = '_'.join([item.tag_id, android_arch(item.abi)])
    elif item.package_type == 'add_on':
        package_name = item.name_id
    else:
        package_name = item.package_type
    return package_name.replace('_', '-')

def get_android_version(item):
    try:
        return (int(item.api_level), item.revision)
    except AttributeError:
        revision = item.revision
        try:
            return (revision.major, revision.minor, revision.micro)
        except AttributeError:
            return (int(revision),)

def get_android_items(url_file_objs):
    items = [];
    for android_file_obj in url_file_objs:
        android_xmldict = xmltodict.parse(android_file_obj.read())
        nodes = next(iter(android_xmldict.values()))

        license_node = wrap_to_list(nodes.pop('sdk:license'))
        licenses = {node['@id']: node['#text'] for node in license_node}

        for key, value in nodes.items():
            if not key.startswith('sdk:'):
                continue
            name = key.replace('sdk:', '', 1).replace('-', '_')
            node_list = wrap_to_list(value)

            for subnode in node_list:
                itm = normalize_xmldict(subnode)
                itm.package_type = name
                itm.package_repo_url = android_file_obj.url

                if len(list(itm.archives.keys())) == 1:
                    itm.archives = wrap_to_list(itm.archives.archive)
                else:
                    raise Exception('archives must contain only archive node')

                for archive in itm.archives:
                    hash_type = archive.checksum['@type']
                    archive.checksum[hash_type] = archive.checksum['#text']
                    del archive.checksum['@type']
                    del archive.checksum['#text']

                license_name = itm.uses_license['@ref']
                itm.license = AttrDict()
                itm.license.name = license_name
                itm.license.content = licenses[license_name]
                del itm.uses_license

                items.append(itm)
    return items

source_property_mapping = (
        ('abi'                , 'SystemImage.Abi'),
        ('api_level'          , 'AndroidVersion.ApiLevel'),
        ('description'        , 'Pkg.Desc'),
        ('layoutlib.api'      , 'Layoutlib.Api'),
        ('layoutlib.revision' , 'Layoutlib.Revision'),
        ('license.content'    , 'Pkg.License'),
        ('license.name'       , 'Pkg.LicenseRef'),
        ('min_tools_rev.major' , 'Platform.MinToolsRev'),
        ('name_display'       , 'Addon.NameDisplay'),
        ('name_id'            , 'Addon.NameId'),
        ('package_repo_url'   , 'Pkg.SourceUrl'),
        ('revision'           , 'Pkg.Revision'),
        ('tag_display'        , 'SystemImage.TagDisplay'),
        ('tag_id'             , 'SystemImage.TagId'),
        ('vendor_display'     , 'Addon.VendorDisplay'),
        ('vendor_id'          , 'Addon.VendorId'),
        ('version'            , 'Platform.Version'),
)

def get_source_properties(item):
    property_dict = dict()

    for xml_key, property_key in source_property_mapping:
        value = item
        try:
            for key in xml_key.split('.'):
                value = value[key]
        except KeyError:
            continue
        property_dict[property_key] = value
    property_dict = collections.OrderedDict(sorted(property_dict.items(),
        key=lambda x: x[0]))

    properties = "#{}".format(datetime.datetime.utcnow().strftime('%c'))
    for key, value in property_dict.items():
        key = re.sub(r'([\#!=:])', r'\\\1', key)
        value = re.sub(r'([\#!=:])', r'\\\1', value)

        key = re.sub(r'\n', r'\\n', key)
        value = re.sub(r'\n', r'\\n', value)
        properties = '{}\n{}={}'.format(properties, key, value)
    return properties

def to_aur_package_name(name):
    if name == 'armeabi-v7a-system-image':
        name = 'armv7a-eabi-system-image'
    return '-'.join(['android', name])

def extract_array_var_pattern(bash_script, varname):
    orig = next(re.finditer(r'{}\=\([^)]+\)'.format(re.escape(varname)),
        bash_script, re.MULTILINE)).group(0)
    patt = re.sub(r'([{}])', r'\1\1', orig, re.MULTILINE)
    patt = re.sub(r'''(["'])((?!\1).)*\1''', r'\1{}\1', patt, re.MULTILINE)
    return orig, patt

def extract_ordinary_var_pattern(bash_script, varname):
    regex_pattern = r'''({}\=)(?P<quote>["']?)((?#
                no quotation
            )(?<=[^"'])[^\s#]+|(?#
                with quotation
            )(?<=["'])((?!(?P=quote)).)*(?P=quote))'''.format(re.escape(varname))
    orig = next(re.finditer(regex_pattern,
        bash_script, re.MULTILINE)).group(0)
    patt = re.sub(r'([{}])', r'\1\1', orig, re.MULTILINE)
    patt = re.sub(regex_pattern, r'\1\g<quote>{}\g<quote>', patt, re.MULTILINE)
    return orig, patt

def update_package(src_path, item):
    try:
        api_level = item.api_level
        rev = 'r{:0>2}'.format(int(item.revision))
        pkgver = '{}_{}'.format(api_level, rev)
    except AttributeError:
        revision = item.revision
        rev = '{}.{}.{}'.format(revision.major, revision.minor, revision.micro)
    for archive in item.archives:
        try:
            host_os = archive['@os']
        except KeyError:
            try:
                host_os = archive.host_os
            except AttributeError:
                host_os = 'any'

        if host_os in ('any', 'linux'):
            break
    else:
        return

    checksum_algo_name, checksum_algo_res = list(archive.checksum.items())[0]

    source_properties_filename = 'source.properties'
    source_properties_path = os.path.join(src_path, source_properties_filename)
    source_properties_list = []
    source_properties_hash_list = []
    if os.path.exists(source_properties_path):
        source_properties = get_source_properties(item)
        source_properties_hash = hashlib.new(checksum_algo_name)
        source_properties_hash.update(bytes(source_properties, 'utf8'))
        source_properties_hash = source_properties_hash.hexdigest()

        source_properties_list.append(source_properties_filename)
        source_properties_hash_list.append(source_properties_hash)

    pkgbuild_path = os.path.join(src_path, 'PKGBUILD')
    with open(pkgbuild_path, 'r') as pkgbuild:
        pkgbuild_content = pkgbuild.read()

        already_updated = True
        try:
            pkg_apilevel, patt = extract_ordinary_var_pattern(pkgbuild_content,
                '_apilevel')
            new_pkg_apilevel = patt.format(api_level)
        except NameError:
            pass
        else:
            pkgbuild_content = pkgbuild_content.replace(pkg_apilevel, new_pkg_apilevel)
            already_updated = (already_updated
                    and pkg_apilevel == new_pkg_apilevel)

        pkg_rev, patt = extract_ordinary_var_pattern(pkgbuild_content, '_rev')
        new_pkg_rev = patt.format(rev)
        pkgbuild_content = pkgbuild_content.replace(pkg_rev, new_pkg_rev)
        already_updated = already_updated and pkg_rev == new_pkg_rev

        pkgname = re.search(r'(?<=pkgname\=)[^\s#]+', pkgbuild_content).group()

        if already_updated:
            print('{} already updated'.format(pkgname))
            return

        pkgsource = [urllib.parse.urljoin(item.package_repo_url, archive.url)]
        pkgsums = [checksum_algo_res]

        pkgsource.extend(source_properties_list)
        pkgsums.extend(source_properties_hash_list)

        pkgbuild_content = re.sub(r'(?<=pkgrel\=)[^\n]+', '1',
                pkgbuild_content, flags=re.MULTILINE)

        for varname, values in zip(['source',
            '{}sums'.format(checksum_algo_name)], [pkgsource, pkgsums]):
            bash_array, array_pattern = extract_array_var_pattern(
                pkgbuild_content, varname)
            pkgbuild_content = pkgbuild_content.replace(bash_array,
                    array_pattern.format(*values))


    with open(pkgbuild_path, 'w') as pkgbuild:
        pkgbuild.write(pkgbuild_content)

    if source_properties_list:
        with open(source_properties_path, 'w') as f:
            f.write(source_properties)

    cwd = os.getcwd()
    os.chdir(src_path)
    try:
        git_command = 'git commit'.split()
        git_command.extend(source_properties_list + ['PKGBUILD'])
        git_command.extend([
            '-m','Update pkg ({pkgver})'.format(pkgname=pkgname, pkgver=pkgver)])
        subprocess.check_call(git_command)
    except subprocess.CalledProcessError:
        pass
    finally:
        os.chdir(cwd)

def main(argv):
    directory = argv[1]

    package_list_open_urls = [urllib.request.urlopen(i)
            for i in itertools.chain.from_iterable(get_addon_urls().values())]
    package_list_open_urls.append(open_repository_xml_url())

    android_items = get_android_items(package_list_open_urls)
    android_items = [item for item in android_items
            if item.package_type != 'extra' and 'obsolete' not in item]
    items_by_package_name = itertools.groupby(android_items,
            get_android_package_name)

    latest_packages = {package_name: list(sorted(items,
        key=get_android_version, reverse=True))[0]
        for package_name, items in items_by_package_name}

    for package_name, item in latest_packages.items():
        try:
            update_package(os.path.join(directory,
                to_aur_package_name(package_name)), item)
        except FileNotFoundError:
            pass

if __name__ == '__main__':
    main(sys.argv)
