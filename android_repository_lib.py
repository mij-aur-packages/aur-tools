import collections
import datetime
import hashlib
import os
import pkgbuild_lib
import re
import sys
import urllib, urllib.error, urllib.request
import xml.etree.ElementTree as etree
import xmltodict


def namespace_format(namespace, tag):
    return '{{{namespace}}}{tag}'.format(namespace=namespace, tag=tag)

def get_latest_url(url_pattern, num_max=None, delim='-'):
    """Return a request object for the latest url available for consumption.
    The url is constructed by formatting `url_pattern` with `delim` and an
    index ranging from 1 to `num_max`, inclusive. The latest url is obtained by
    finding the highest index in which the constructed url successfully return."""
    if num_max is not None:
        for i in range(num_max, 0, -1):
            url_to_be_open = url_pattern.format(delim=delim, num=i)
            try:
                return urllib.request.urlopen(url_to_be_open)
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise e
    return urllib.request.urlopen(url_pattern.format(delim='', num=''))

def get_addon_url_paths(num_max=3):
    """Return a dictionary which maps the addon name to its url from the latest
    repository. The url for the repository is obtained by the url whose index
    is the highest and would make a successful request. The index ranges from 1
    to `num_max`, inclusive"""
    android_addons_list_xml_url_pattern = (
            'https://dl-ssl.google.com/android/repository/addons_list{delim}{num}.xml')
    addons_list_file_obj = get_latest_url(android_addons_list_xml_url_pattern,
        num_max=num_max)
    root = etree.parse(addons_list_file_obj).getroot()
    namespace = re.match(r'\{([^}]+)}', root.tag).group(1)

    urls = {}
    for node in root:
        url_node = node.find('url')
        name_node = node.find('displayName')
        url = urllib.parse.urljoin(
                'http://dl-ssl.google.com/android/repository/', url_node.text)
        urls.setdefault(name_node.text, []).append(url)
    return urls

def get_repository_xml_url(num_max=12):
    """Return a request object the latest repository. The url for the
    repository is obtained by the url whose index is the highest and would
    make a successful request. The index ranges from 1 to `num_max`, inclusive"""
    android_repository_xml_url_pattern = (
            'https://dl-ssl.google.com/android/repository/repository{delim}{num}.xml')
    return get_latest_url(
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

def create_or_return_list(obj, expected_types=None):
    """Return the object if it is a list. Otherwise, wrap the object in a
    list. If the `expected_types` is not None, `obj` must be an instance of one
    of the types in the list in order for the call to succeed."""
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
        return 'armv7a-eabi'
    return arch


def get_android_package_name(item):
    if item.package_type == 'system_image':
        if item.tag_id == 'default':
            package_name = '_'.join([android_arch(item.abi), item.package_type])
        else:
            package_name = '_'.join([item.tag_id, android_arch(item.abi)])
    elif item.package_type == 'add_on':
        package_name = item.name_id
    elif item.package_type == 'source':
        package_name = 'sources'
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

        if ('repo:sdk-addon' in android_xmldict
                or 'sys-img:sdk-sys-img' in android_xmldict):
            get_android_items_2(android_file_obj, android_xmldict, nodes, items)
        else:
            get_android_items_o(android_file_obj, android_xmldict, nodes, items)

    return items

def get_android_items_o(android_file_obj, android_xmldict, nodes, items):
    license_node = create_or_return_list(nodes.pop('sdk:license'))
    licenses = {node['@id']: node['#text'] for node in license_node}

    for key, value in nodes.items():
        if not key.startswith('sdk:'):
            continue
        name = key.replace('sdk:', '', 1).replace('-', '_')
        node_list = create_or_return_list(value)

        for subnode in node_list:
            itm = normalize_xmldict(subnode)
            itm.package_type = name
            itm.package_repo_url = android_file_obj.url

            if len(list(itm.archives.keys())) == 1:
                itm.archives = create_or_return_list(itm.archives.archive)
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

def get_android_items_2(android_file_obj, android_xmldict, nodes, items):
    license_node = create_or_return_list(nodes.pop('license'))
    licenses = {node['@id']: node['#text'] for node in license_node}
    if 'sys-img:sdk-sys-img' in android_xmldict:
        package_type = 'sys-img'
    elif 'repo:sdk-addon':
        package_type = 'addon'

    for key, value in nodes.items():
        if key != 'remotePackage':
            continue
        node_list = create_or_return_list(value)

        for subnode in node_list:
            itm = normalize_xmldict(subnode)
            itm.package_type = package_type
            itm.package_repo_url = android_file_obj.url

            if len(list(itm.archives.keys())) == 1:
                itm.archives = create_or_return_list(itm.archives.archive)
            else:
                raise Exception('archives must contain only archive node')

            for archive in itm.archives:
                archive.checksum['sha1'] = archive.complete.checksum
                del archive.complete.checksum

            # TODO: do not merge type details on the parent node
            itm.update(itm.type_details)
            del itm.type_details

            license_name = itm.uses_license['@ref']
            itm.license = AttrDict()
            itm.license.name = license_name
            itm.license.content = licenses[license_name]
            del itm.uses_license

            items.append(itm)

source_property_mapping = (
        ('abi'                    , 'SystemImage.Abi'),
        ('add_on.vendor_display'  , 'Addon.VendorDisplay'),
        ('add_on.vendor_id'       , 'Addon.VendorId'),
        ('api_level'              , 'AndroidVersion.ApiLevel'),
        ('description'            , 'Pkg.Desc'),
        ('layoutlib.api'          , 'Layoutlib.Api'),
        ('layoutlib.revision'     , 'Layoutlib.Revision'),
        ('license.content'        , 'Pkg.License'),
        ('license.name'           , 'Pkg.LicenseRef'),
        ('min_tools_rev.major'    , 'Platform.MinToolsRev'),
        ('name_display'           , 'Addon.NameDisplay'),
        ('name_id'                , 'Addon.NameId'),
        ('package_repo_url'       , 'Pkg.SourceUrl'),
        ('revision'               , 'Pkg.Revision'),
        ('tag_display'            , 'SystemImage.TagDisplay'),
        ('tag_id'                 , 'SystemImage.TagId'),
        ('vendor_display'         , 'Addon.VendorDisplay'),
        ('vendor_id'              , 'Addon.VendorId'),
        ('version'                , 'Platform.Version'),
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


def get_android_package_pkgver_vars(item):
    """Returns a dictionary mapping the '_rev' variable with the revision's
    major, minor and micro value or the revision's value if those are not
    available, '_apilevel' with the api_level if its available, and the
    pkgver."""
    version_variables = {}
    try:
        version_variables['_apilevel'] = item.api_level
        version_variables['_rev'] = 'r{:0>2}'.format(int(item.revision))
        version_variables['pkgver'] = '{}_{}'.format(version_variables['_apilevel'],
                version_variables['_rev'])
    except AttributeError:
        revision = item.revision
        version_variables['_rev'] = '{}.{}.{}'.format(revision.major, revision.minor, revision.micro)
        version_variables['pkgver'] = '{}'.format(version_variables['_rev'])
    return version_variables


def update_package(run, src_path, item):
    # Skip package when the host os is not compatible with linux
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

    pkgbuild_path = os.path.join(src_path, 'PKGBUILD')
    with open(pkgbuild_path, 'r') as pkgbuild:
        pkgbuild_content = pkgbuild.read()

    pkgname = pkgbuild_lib.get_pkgbuild_value(pkgbuild_content, 'pkgname')

    android_pkgver_vars = get_android_package_pkgver_vars(item)
    android_pkgver = android_pkgver_vars['pkgver']
    del android_pkgver_vars['pkgver']

    has_update = False
    try:
        pkgbuild_apilevel = pkgbuild_lib.get_pkgbuild_value(pkgbuild_content, '_apilevel')
        has_update = has_update or pkgbuild_lib.vercmp(run, pkgbuild_apilevel,
            android_pkgver_vars['_apilevel']) < 0
    except ValueError:
        pass

    pkgbuild_rev = pkgbuild_lib.get_pkgbuild_value(pkgbuild_content, '_rev')
    has_update = has_update or pkgbuild_lib.vercmp(run, pkgbuild_rev,
            android_pkgver_vars['_rev']) < 0

    if not has_update:
        print('{} already updated'.format(pkgname))
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


    for varname, value in android_pkgver_vars.items():
        pkgbuild_content = pkgbuild_lib.replace_pkgbuild_var_value(
                pkgbuild_content, varname, value)
    pkgbuild_content = pkgbuild_lib.replace_pkgbuild_var_value(
            pkgbuild_content, 'pkgrel', '1')

    pkgsource = [urllib.parse.urljoin(item.package_repo_url, archive.url)]
    pkgsums = [checksum_algo_res]

    pkgsource.extend(source_properties_list)
    pkgsums.extend(source_properties_hash_list)

    for varname, values in zip(['source',
        '{}sums'.format(checksum_algo_name)], [pkgsource, pkgsums]):
        bash_array, array_pattern = pkgbuild_lib.extract_array_var_pattern(
            pkgbuild_content, varname)
        pkgbuild_content = pkgbuild_content.replace(bash_array,
                array_pattern.format(*values))

    with open(pkgbuild_path, 'w') as pkgbuild:
        pkgbuild.write(pkgbuild_content)

    if source_properties_list:
        with open(source_properties_path, 'w') as f:
            f.write(source_properties)
    pkgbuild_lib.commit_pkgbuild(run, src_path,
            pkgname, android_pkgver, source_properties_list)
