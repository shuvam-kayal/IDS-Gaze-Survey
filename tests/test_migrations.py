from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def _script_directory() -> ScriptDirectory:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    return ScriptDirectory.from_config(config)


def test_migration_graph_has_one_head_and_unique_revisions():
    script = _script_directory()
    revisions = list(script.walk_revisions())
    revision_ids = [revision.revision for revision in revisions]
    assert len(revision_ids) == len(set(revision_ids))
    assert script.get_heads() == ["20261021_0007"]


def test_existing_p3_revision_is_the_ancestor_of_new_p2_chain():
    script = _script_directory()
    control_plane = script.get_revision("20261020_0001")
    study_configs = script.get_revision("20261020_0002")
    experience_config = script.get_revision("20261020_0003")
    assert control_plane.down_revision == "20261019_0003"
    assert study_configs.down_revision == control_plane.revision
    assert experience_config.down_revision == study_configs.revision
    assert script.get_revision("20261019_0003").path.endswith("20261019_0003_scope_gaze_associations.py")
