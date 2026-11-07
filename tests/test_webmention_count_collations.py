"""Count real rows under default and deliberately permissive DB collations."""

import unicodedata

import pytest
from django.db import connection
from django.db.models import Count
from django.template import Context, Template

from indieweb.models import Webmention
from indieweb.templatetags.webmention_tags import prepare_webmention_counts, webmention_count


@pytest.fixture(params=[False, True], ids=["default-collation", "insensitive-collation"])
def count_collation(request, transactional_db):
    if not request.param:
        yield False
        return

    name = "indieweb_test_insensitive"
    if connection.vendor == "sqlite":

        def key(value):
            return "".join(
                c for c in unicodedata.normalize("NFD", value.casefold().rstrip()) if not unicodedata.combining(c)
            )

        connection.connection.create_collation(name, lambda a, b: (key(a) > key(b)) - (key(a) < key(b)))
    elif connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                f'CREATE COLLATION "{name}" (provider = icu, '
                "locale = 'und-u-ka-shifted-ks-level1', deterministic = false)"
            )
    else:
        pytest.skip("Collation regression runs on SQLite and PostgreSQL")

    changed = []
    try:
        for field_name in ("target_url", "mention_type", "status"):
            original = Webmention._meta.get_field(field_name)
            altered = original.clone()
            altered.set_attributes_from_name(field_name)
            altered.db_collation = name
            with connection.schema_editor() as editor:
                editor.alter_field(Webmention, original, altered)
            changed.append((original, original.db_collation))
            original.db_collation = name
        yield True
    finally:
        for original, old_collation in reversed(changed):
            restored = original.clone()
            restored.set_attributes_from_name(original.name)
            restored.db_collation = old_collation
            with connection.schema_editor() as editor:
                editor.alter_field(Webmention, original, restored)
            original.db_collation = old_collation
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute(f'DROP COLLATION "{name}"')
        else:
            connection.connection.create_collation(name, None)


def test_counts_use_exact_strings_on_both_backends(count_collation, django_assert_num_queries):
    urls = [f"https://example.test/{path}" for path in ("post", "POST", "póst", "post ", "po\u0301st")]
    absent = "https://example.test/Post"
    expected = {url: {"reply": i + 1, "like": 1, "REPLY": 1} for i, url in enumerate(urls)}
    expected[absent] = {}
    for url, by_type in expected.items():
        for kind, total in by_type.items():
            for _ in range(total):
                Webmention.objects.create(
                    source_url=f"https://source.test/{Webmention.objects.count()}",
                    target_url=url,
                    status="verified",
                    mention_type=kind,
                )
        for status in ("pending", "VERIFIED"):
            Webmention.objects.create(
                source_url=f"https://source.test/{Webmention.objects.count()}",
                target_url=url,
                status=status,
                mention_type="reply",
            )

    # Prove this is a real SQL equivalence collision, rather than mocked rows.
    with connection.cursor() as cursor:
        comparison = "SELECT %s = %s COLLATE indieweb_test_insensitive" if count_collation else "SELECT %s = %s"
        cursor.execute(comparison, [urls[0], urls[1]])
        assert bool(cursor.fetchone()[0]) is count_collation
    groups = list(Webmention.objects.order_by().values("target_url").annotate(total=Count("pk")))
    assert len(groups) == (1 if count_collation else len(expected))

    with django_assert_num_queries(1):
        counts = prepare_webmention_counts([*expected, urls[0], ""])
    assert counts == expected
    for url, by_type in expected.items():
        for kind in (None, "reply", "like", "REPLY", "unknown", "réply", "reply "):
            wanted = sum(by_type.values()) if kind is None else by_type.get(kind, 0)
            with django_assert_num_queries(0):
                assert webmention_count({"webmention_counts": counts}, url, kind) == wanted
            with django_assert_num_queries(1):
                assert webmention_count({}, url, kind) == wanted

    template = Template("""{% load webmention_tags %}{% prepare_webmention_counts urls as webmention_counts %}
        {% for url in urls %}{% webmention_count url %},{% webmention_count url 'reply' %};{% endfor %}""")
    with django_assert_num_queries(1):
        output = template.render(Context({"urls": list(expected)}))
    assert output.strip() == "".join(f"{sum(kinds.values())},{kinds.get('reply', 0)};" for kinds in expected.values())
