import argparse
import re
import shutil
import os

from os.path import abspath, isdir

from lxml import etree, html
from path import Path

import chm


def can_skip_section(section):
    for sec in section.findall('section'):
        if sec.get('title') not in (
            'List of all members',
            'Obsolete members'
        ):
            return False
    return True

def parse_file_toc(file, parent):
    if not file.exists():
        return
    with open(file, encoding='utf-8') as f:
        tree = html.parse(f)

    for toc in tree.xpath('//div[@class="toc"]'):
        prev_level = None
        prev_item = None
        stack = [parent]
        for li in toc.findall('ul/li'):
            level = int(li.get('class')[-1])
            # some HTML have 2 as the first level
            if prev_level is None:
                prev_level = level
            a = li.find('a')
            title = html.tostring(a, encoding='unicode', method='text').strip()
            href = a.get('href')

            # qtcore\qromancalendar.html has one <a href="#"></a> TOC entry that doesn't make any sense
            if href[0] == '#' and not title:
                continue

            if href[0] == '#':
                href = file.basename() + href
            href = OUTPUT.relpathto(file.dirname() / href)

            if level > prev_level:
                stack.append(prev_item)
            elif level < prev_level:
                for i in range(level, prev_level):
                    stack.pop()
            item = stack[-1].append(title, href)

            prev_level = level
            prev_item = item

    if file.basename() == 'qtexamplesandtutorials.html':
        for multicolumn in tree.xpath('//div[@class="multi-column"]'):
            for doccolumn in multicolumn.findall('div[@class="doc-column"]'):
                title = html.tostring(doccolumn.find('p'), encoding='unicode', method='text').strip()
                doccolumn_toc = parent.append(title, OUTPUT.relpathto(file))
                for li in doccolumn.findall('ul/li'):
                    a = li.find('a')

                    # Some entries are missing as links sometimes
                    if a is None:
                        continue

                    href = a.get('href')
                    if href.startswith('http://doc.qt.io'):
                        continue
                    title = html.tostring(a, encoding='unicode', method='text').strip()
                    doccolumn_toc.append(title, OUTPUT.relpathto(file.dirname() / href))

def process_section(elem, parent, module):
    for section in elem.findall('section'):
        title = section.get('title').strip()

        # qtcore5 empty ref workaround
        if module.basename() in ("qtcore5", "qtcore5compat") and title == "C++ Classes" and not section.get('ref'):
            title = ""

        # nonexistant
        if module.basename() == "qtshadertools" and title == "Examples" and not section.get('ref'):
            continue

        # title could be empty
        if title:
            # Workaround, there is only 1 glitch like this so far in qtdatavisualization\qtdatavis3d.qhp
            if not section.get('ref'):
                if module.basename() == "qtdatavisualization" and title == "Getting Started":
                    section.set("ref", "qtdatavisualization-index.html")
                else:
                    raise RuntimeError(f"Empty reference in {module}")

            href = module.basename() / section.get('ref')

            # skip entries referencing deprecated stuff
            file_path = SOURCE / href
            if not file_path.exists():
                continue

            child_toc = parent.append(title, href)
        else:
            child_toc = parent
        if not can_skip_section(section):
            process_section(section, child_toc, module)
        elif '#' not in href:
            parse_file_toc(OUTPUT / href, child_toc)

def process_qhp(file, module):
    # print('Processing QHP', file)
    with open(file, encoding='utf-8'):
        tree = etree.parse(file)
    toc = tree.xpath('//toc')
    if len(toc):
        process_section(toc[0], CHM.toc, module)
    keywords = tree.xpath('//keywords')
    index = CHM.index
    if len(keywords):
        for keyword in keywords[0].findall('keyword'):
            name = keyword.get('name')

            # too many topics
            if name.startswith('operator') and ' ' not in name:
                continue

            href = module.basename() / keyword.get('ref')

            # skip keywords referencing deprecated stuff
            file_path = SOURCE / href.partition("#")[0]
            if not file_path.exists():
                continue

            title = keyword.get('ref')
            index.append(name, href, title)

def process_resource(dir, output_dir):
    if dir.basename() == 'style':
        return

    target = output_dir / dir.basename()

    if not target.exists():
        # print('Copying', dir)
        shutil.copytree(dir, target)

    for file in target.files():
        if dir.basename() == 'images' and file.basename() in STYLE_IMAGES:
            os.remove(file)
            continue

        CHM.append(OUTPUT.relpathto(file))

    # remove image directory that only had style pics
    if target.basename() == 'images' and not target.files():
        os.rmdir(target)

style_re = re.compile(r'<link.*?</script>', re.S)
root_link = re.compile(r'(<div class="navigationbar">\s*<table><tr>\s*)<td >([^<]*?)</td>', re.M)

def process_html(file, output_dir):
    target = output_dir / file.basename()
    if not target.exists():
        # print('Processing HTML', file)
        with open(file, encoding='utf-8') as r, open(target, 'w', encoding='utf-8') as w:
            content = r.read()
            # remove stylesheet set via javascript
            content = style_re.sub('<link rel="stylesheet" type="text/css" href="../{}" />'.format(STYLE_FILE.basename()), content, 1)

            # fix missing root href in navigation bar
            root_link_match = root_link.search(content)
            if root_link_match:
                content = root_link.sub(root_link_match.group(1) + '<td ><a href="../qtdoc/index.html">' + root_link_match.group(2) + '</a></td>', content, 1)

            # remove empty paragraph after navigation button
            content = content.replace('</p><p/>', '</p>')
            w.write(content)
    CHM.append(OUTPUT.relpathto(target))

def process_module(module):
    print("Processing module", module)

    output_dir = OUTPUT / module.basename()
    output_dir.mkdir_p()

    qhp = None
    for file in module.files():
        if file.ext == '.html':
            process_html(file, output_dir)
        elif file.ext == '.qhp':
            qhp = file

    if qhp:
        process_qhp(qhp, module)

    for dir in module.dirs():
        process_resource(dir, output_dir)

def main():
    global SOURCE
    global OUTPUT
    global STYLE_FILE
    global STYLE_IMAGES
    global CHM

    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--style', required=True, help="Style sheet for docs")
    parser.add_argument('docs_source', help="QT docs source directory")
    parser.add_argument('docs_out', help="Output directory for chm files")
    args = parser.parse_args()

    SOURCE = Path(args.docs_source).abspath()
    OUTPUT = Path(args.docs_out).abspath()
    STYLE_FILE = Path(args.style).abspath()

    with open(SOURCE / 'qtdoc' / 'qtdoc.index', encoding='utf-8') as r:
        qt_version = re.search(r'<INDEX.*version="(.*?)"', r.read())

        if not qt_version:
            raise RuntimeError("Failed to parse QT Docs version")

        qt_version = qt_version.group(1)

    STYLE_IMAGES = (
        "ico_out.png",
        "ico_note.png",
        "ico_note_attention.png",
        "btn_prev.png",
        "btn_next.png",
        "home.png",
        "arrow_bc.png",
        "bgrContent.png",
        "bullet_dn.png",
        "bullet_sq.png",
        "logo.png",
    )

    CHM = chm.DocChm(f'Qt-{qt_version}', default_topic='qtdoc/index.html', title=f'Qt {qt_version}')

    OUTPUT.mkdir_p()

    images_dir = OUTPUT / 'images'

    images_dir.mkdir_p()

    for image in STYLE_IMAGES:
        shutil.copy(SOURCE / 'qtdoc' / 'images' / image, images_dir / image)

    # put qtdoc first
    process_module(SOURCE / 'qtdoc')

    excluded_dirs = ('config', 'global', 'qtdoc')

    for module in SOURCE.dirs():
        if module.basename() not in excluded_dirs:
            process_module(module)

    shutil.copy(STYLE_FILE, OUTPUT / STYLE_FILE.basename())

    for image in STYLE_IMAGES:
        CHM.append(f"images\{image}")

    CHM.append(STYLE_FILE.basename())

    with OUTPUT:
        CHM.save()

    print(f"QT Docs v.{qt_version} are ready for CHM compilation")


if __name__ == '__main__':
    main()
