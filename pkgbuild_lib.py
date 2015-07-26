import os
import re
import shlex
import subprocess


def vercmp(run, ver1, ver2):
    vercmp_res = run('vercmp {} {}'.format(ver1, ver2))
    return int(vercmp_res)


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
    try:
        orig = next(re.finditer(regex_pattern,
            bash_script, re.MULTILINE)).group(0)
    except StopIteration:
        raise ValueError('Variable "{}" not found in the script'.format(varname))
    patt = re.sub(r'([{}])', r'\1\1', orig, re.MULTILINE)
    patt = re.sub(regex_pattern, r'\1\g<quote>{}\g<quote>', patt, re.MULTILINE)
    return orig, patt

def get_value_of_ordinary_var(extracted_ordinary_var_value):
    extracted = extracted_ordinary_var_value.split('=', maxsplit=1)[1]
    value = shlex.split(extracted, comments=True, posix=False)[0]
    # Remove quotes if there are any
    for quote in ["'", '"']:
        if value[0] == quote and value[-1] == quote:
            value = value[1:-1]
            break
    return value

def get_pkgbuild_value(pkgbuild_content, var_name):
    extracted = extract_ordinary_var_pattern(pkgbuild_content, var_name)[0]
    return get_value_of_ordinary_var(extracted)

def replace_pkgbuild_var_value(pkgbuild_content, var_name, var_value):
    orig_var_and_var_value, patt = extract_ordinary_var_pattern(
            pkgbuild_content, var_name)
    return pkgbuild_content.replace(orig_var_and_var_value,
            patt.format(var_value))

def commit_pkgbuild(run, src_path, pkgname, pkgver, other_files):
    cwd = os.getcwd()
    os.chdir(src_path)
    try:
        git_command = 'git commit'.split()
        git_command.extend(other_files + ['PKGBUILD'])
        git_command.extend([
            '-m',"'Update pkg ({pkgver})'".format(pkgname=pkgname, pkgver=pkgver)])
        run(' '.join(git_command))
    except subprocess.CalledProcessError:
        pass
    finally:
        os.chdir(cwd)
