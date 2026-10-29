"""Check deployable bindings and documented interfaces without invoking a solver."""
import json
from pathlib import Path
import re
import shlex
import unittest
from unittest.mock import patch
from urllib.parse import unquote

ROOT=Path(__file__).resolve().parents[1]
NEW={'fem':'run-mlcc-fem','phase_field':'run-mlcc-phase-field',
     'rve':'run-mlcc-rve','spice':'run-mlcc-spice'}

def frontmatter(path):
    text=path.read_text(encoding='utf-8')
    header=text.split('---',2)[1]
    return dict(line.split(':',1) for line in header.splitlines() if ':' in line)

class SkillPackagingTests(unittest.TestCase):
    def test_bundle_and_agent_bind_same_eight_real_skills(self):
        manifest=json.loads((ROOT/'bundle.json').read_text(encoding='utf-8'))
        names=manifest['agent']['skills']
        agent=frontmatter(ROOT/manifest['agent']['entry'])
        self.assertEqual(len(names),len(set(names)))
        self.assertEqual(set(names),{s.strip() for s in agent['skills'].split(',')})
        self.assertEqual(set(names),set(NEW.values())|{'run-mlcc-dft','run-mlcc-md','model-mlcc-structures','compute-mlcc-properties'})
        self.assertFalse((ROOT/'skills/run-mlcc-scales').exists())
        for name in names:
            metadata=frontmatter(ROOT/'skills'/name/'SKILL.md')
            self.assertEqual(metadata['name'].strip(),name)
            self.assertTrue(metadata['description'].strip())

    def test_live_module_operations_are_documented_by_their_own_skill(self):
        for module,name in NEW.items():
            manifest=json.loads((ROOT/'modules'/module/'module.json').read_text(encoding='utf-8'))
            text=(ROOT/'skills'/name/'SKILL.md').read_text(encoding='utf-8')
            documented=set(re.findall(r'`([a-z][a-z0-9_]*)`',text))
            self.assertTrue(set(manifest['operations'])<=documented,(module,set(manifest['operations'])-documented))

    def test_skill_and_method_links_resolve_inside_bundle(self):
        paths=[ROOT/'agents/mlcc/AGENT.md',ROOT/'skills/compute-mlcc-properties/SKILL.md',
               ROOT/'skills/references/task-lifecycle.md']
        paths += [ROOT/'skills'/name/'SKILL.md' for name in NEW.values()]
        paths += list((ROOT/'modules').glob('*/skills/*/SKILL.md'))
        for path in paths:
            text=path.read_text(encoding='utf-8')
            for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',text):
                if '://' in target:continue
                filename,_,anchor=target.partition('#')
                resolved=(path.parent/unquote(filename)).resolve() if filename else path
                self.assertTrue(resolved.is_relative_to(ROOT.resolve()),(path,target))
                self.assertTrue(resolved.is_file(),(path,target))
                if anchor and resolved.suffix=='.md':
                    headings=re.findall(r'^#+\s+(.+)$',resolved.read_text(encoding='utf-8'),re.M)
                    slugs={re.sub(r'[^\w\- ]','',h.lower()).replace(' ','-') for h in headings}
                    self.assertIn(unquote(anchor),slugs,(path,target))

    def test_documented_command_blocks_parse_without_backend_calls(self):
        from mlcc.cli import build_parser
        parser=build_parser()
        paths=[ROOT/'skills'/name/'SKILL.md' for name in NEW.values()]
        paths.append(ROOT/'skills/references/task-lifecycle.md')
        commands=[]
        for path in paths:
            for block in re.findall(r'```sh\n(.*?)```',path.read_text(encoding='utf-8'),re.S):
                commands.extend(line for line in block.splitlines() if line.startswith('mlcc '))
        self.assertTrue(commands)
        with patch('subprocess.run',side_effect=AssertionError('Documentation checks must not execute')):
            for command in commands:parser.parse_args(shlex.split(command)[1:])

if __name__=='__main__':unittest.main()
