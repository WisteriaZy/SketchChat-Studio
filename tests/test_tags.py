import unittest
from test_studio import Fixture
from sketchbook.chat import select_tag
from sketchbook.tags import validate_tag

class TagTests(Fixture):
    def test_only_start_matches(self):
        for text in ('正文#普通#','正文 #普通# 之后',' #普通# 内容','\n#普通# 内容'):
            self.assertEqual(select_tag(self.character,'old',text),('old',text))
        self.assertEqual(select_tag(self.character,'old','#普通# 内容'),(self.expression['id'],'内容'))
    def test_body_tags_and_trailing_spaces_are_preserved(self):
        self.assertEqual(select_tag(self.character,'old','#普通# 正文 #普通#  '),(self.expression['id'],'正文 #普通#  '))
    def test_custom_tags_roundtrip(self):
        for tag in ('/开心','[开心]',':)', 'hi', 'a=b', '.*'):
            self.expression['tag'] = tag
            self.lib.save_character(self.character)
            self.assertEqual(select_tag(self.character,'old',tag+' 内容'),(self.expression['id'],'内容'))
    def test_longest_prefix_wins(self):
        self.expression['tag'] = '/笑'
        second = self.lib.add_expression(self.character,self.source,'大笑')
        second['tag'] = '/笑一下'
        self.lib.save_character(self.character)
        self.assertEqual(select_tag(self.character,'old','/笑一下正文'),(second['id'],'正文'))
    def test_only_one_prefix_is_consumed(self):
        self.expression['tag'] = ':)'
        self.assertEqual(select_tag(self.character,'old',':):)内容'),(self.expression['id'],':)内容'))
        self.assertEqual(select_tag(self.character,'old',':)'),(self.expression['id'],''))
    def test_invalid_tags(self):
        for tag in ('',' ', ' x', 'x ', 'a\nb', '\t', 'a\x00b',None):
            with self.subTest(tag=tag),self.assertRaises(ValueError): validate_tag(tag)
    def test_literal_not_regex(self):
        self.expression['tag'] = '.*'
        self.assertEqual(select_tag(self.character,'old','普通文字'),('old','普通文字'))
