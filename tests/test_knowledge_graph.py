"""Knowledge atlas must never publish unverified or private connections."""
import json
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from knowledge_graph import build_graph


class KnowledgeGraphUnitTests(unittest.TestCase):
    def setUp(self):
        self.topic = {'id':'a'*32,'title':'Логика','group':'Темы'}
        self.person = {'id':'b'*32,'title':'Аристотель','group':'Личности'}
        self.history = {'id':'c'*32,'title':'Античность','group':'История философии'}
        self.private = {'id':'d'*32,'title':'Моя работа','group':'Самостоятельная работа'}
        self.pages = {p['id']:p for p in [self.topic,self.person,self.history,self.private]}
        self.ordered = {'Темы':[self.topic], 'Личности':[self.person],
                        'История философии':[self.history]}
        self.slugs = {self.topic['id']:'topics/logika/',
                      self.person['id']:'people/aristotel/',
                      self.history['id']:'history/antichnost/'}
        self.rows = {
          self.topic['id']:{'Личности':'Аристотель ('+'b'*32+'.md), Аристотель ('+'b'*32+'.md)',
                            'История философии':'Античность ('+'c'*32+'.md)',
                            'Связь':'Моя работа ('+'d'*32+'.md)'},
          self.person['id']:{'Темы':'Логика ('+'a'*32+'.md)',
                            'История философии':''},
          self.history['id']:{'Темы':'', 'Личности':''},
        }

    def test_provenance_and_no_duplicate_undirected_edges(self):
        graph = build_graph(self.pages,self.rows,self.ordered,self.slugs)
        self.assertEqual(len(graph['nodes']),3)
        self.assertEqual(len(graph['edges']),2)
        edge = next(e for e in graph['edges'] if {'a'*32,'b'*32} ==
                    {e['source'],e['target']})
        self.assertEqual(edge['type'],'explicit_relation')
        self.assertEqual(edge['evidence'],[
          {'from':'a'*32,'field':'Личности'},
          {'from':'b'*32,'field':'Темы'},
        ])
        self.assertFalse(any('d'*32 in (e['source'],e['target']) for e in graph['edges']))

    def test_does_not_infer_links_from_unpublished_or_unstructured_text(self):
        self.rows[self.topic['id']]['Личности'] = ''
        self.rows[self.topic['id']]['История философии'] = ''
        self.rows[self.person['id']]['Темы'] = ''
        graph = build_graph(self.pages,self.rows,self.ordered,self.slugs)
        self.assertEqual(graph['edges'],[])

    def test_unpublished_nodes_are_rejected(self):
        self.slugs[self.private['id']] = 'topics/private/'
        with self.assertRaises(ValueError):
            build_graph(self.pages,self.rows,self.ordered,self.slugs)


if __name__ == '__main__':
    unittest.main()
