"""Tests for image prompt composition."""

from novel_to_comic.config import Config
from novel_to_comic.models.layout_plan import PlannedPanel
from novel_to_comic.models.prompt import ImagePrompt, PromptSubject
from novel_to_comic.models.story_bible import Character, Location, Prop, Scene, StoryBible
from novel_to_comic.prompting import (
    build_planned_panel_prompt_spec,
    dimensions_for_panel,
    generate_distilled_prompt,
    render_generation_prompt,
)


def _story_bible() -> StoryBible:
    return StoryBible(
        title="The Flowers",
        author="Alice Walker",
        total_scenes=1,
        characters=[
            Character(
                id="char_001",
                name="Myop",
                visual_anchor=(
                    "1girl, child, black girl, dark skin, brown eyes, short hair, "
                    "afro textured hair, simple dress, barefoot"
                ),
                age_range="ten",
                gender="female",
                distinguishing_features=["dark brown skin"],
                default_outfit="A simple dress. She is barefoot.",
                relationships=[],
                first_appearance_scene="scene_002",
            )
        ],
        locations=[
            Location(
                id="loc_002",
                name="The gloomy cove",
                visual_anchor="outdoors, day, woods, forest, sweetsuds bush",
                mood="gloomy",
            )
        ],
        scenes=[
            Scene(
                id="scene_002",
                chapter=1,
                title="A New Path",
                location_id="loc_002",
                character_ids=["char_001"],
                summary="Myop gathers flowers in the woods.",
                scene_type="transition",
                narrative_beat="inciting_incident",
                source_start_quote="She had explored the woods",
            )
        ],
        narrative_arcs=[],
        props=[
            Prop(
                id="prop_001",
                name="Blue flowers",
                visual_anchor="small vivid blue flowers with velvety petals",
                first_appearance_scene="scene_002",
            )
        ],
    )


def _flowers_story_bible() -> StoryBible:
    return StoryBible(
        title="The Flowers",
        author="Alice Walker",
        total_scenes=1,
        characters=[
            Character(
                id="char_001",
                name="Myop",
                visual_anchor="1girl, child, black skin, short hair, simple dress, barefoot",
                age_range="10",
                gender="female",
                distinguishing_features=["dark brown skin"],
                default_outfit="A simple cotton dress. Barefoot.",
                relationships=[],
                first_appearance_scene="scene_002",
            )
        ],
        locations=[
            Location(
                id="loc_002",
                name="Spring bank",
                visual_anchor="stream, silver ferns, wild flowers, shallow water",
                mood="quiet",
            )
        ],
        scenes=[
            Scene(
                id="scene_002",
                chapter=1,
                title="Spring bank",
                location_id="loc_002",
                character_ids=["char_001"],
                character_appearances={"char_001": "holding a short knobby stick"},
                summary="Myop follows the fence to the stream.",
                scene_type="transition",
                narrative_beat="wandering",
                source_start_quote="She followed the fence",
            )
        ],
        narrative_arcs=[],
        props=[
            Prop(
                id="prop_001",
                name="Knobby Stick",
                visual_anchor="A short, sturdy wooden branch with knobby protrusions.",
                first_appearance_scene="scene_001",
            ),
            Prop(
                id="prop_002",
                name="Bundle of Flowers",
                visual_anchor=(
                    "A large, messy armful of wild forest flora. It is NOT a formal bouquet. "
                    "The bundle is carried awkwardly in the crook of the arm or held against the chest."
                ),
                first_appearance_scene="scene_003",
            ),
        ],
    )


def test_prompt_collapses_sequential_same_character_action_to_single_instant(tmp_path):
    panel = PlannedPanel(
        panel_id="scene_002:panel_002",
        scene_id="scene_002",
        panel_number=2,
        beat_ids=["scene_002:beat_003", "scene_002:beat_004"],
        shot_type="close-up",
        camera_angle="from behind, then low side angle",
        characters_present=["char_001"],
        character_actions={
            "char_001": "crouches to inspect flowers, then rises and buries her face in the sweetsuds buds"
        },
        character_positions={"char_001": "center"},
        background_description="Blue velvety flowers in the foreground.",
        camera_note=(
            "A tight view on her hands and upper body as she lifts the blue flowers, "
            "then leans into the fragrant bush with her bundle crowding her chin."
        ),
        lighting="soft warm filtered light",
        mood="curious delighted",
    )

    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _story_bible())

    assert "buries her face in the sweetsuds buds" in prompt.full_prompt
    assert "rises and buries" not in prompt.full_prompt
    assert "low side angle camera" in prompt.full_prompt
    assert "from behind, then low side angle" not in prompt.full_prompt
    assert "crouches to inspect flowers" not in prompt.full_prompt
    assert "leans into the fragrant bush with her bundle crowding her chin" in prompt.full_prompt
    assert "lifts the blue flowers" not in prompt.full_prompt
    assert "single frozen instant, not a sequence or split-screen" in prompt.constraints


def test_prompt_does_not_split_non_sequential_then_phrase(tmp_path):
    panel = PlannedPanel(
        panel_id="scene_002:panel_001",
        scene_id="scene_002",
        panel_number=1,
        shot_type="wide",
        camera_angle="low angle",
        characters_present=["char_001"],
        character_actions={
            "char_001": "bounces between the trees, veering left then right along no particular path"
        },
        character_positions={"char_001": "center"},
        background_description="Dense woods behind a farmhouse.",
        camera_note="A wide establishing view with the girl darting through the foreground.",
        lighting="warm dappled morning light",
        mood="playful safe",
    )

    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _story_bible())

    assert "veering left then right along no particular path" in prompt.full_prompt


def test_generation_prompt_uses_structured_brief_and_noise_guardrails(tmp_path):
    panel = PlannedPanel(
        panel_id="scene_002:panel_001",
        scene_id="scene_002",
        panel_number=1,
        shot_type="wide",
        camera_angle="low angle",
        characters_present=["char_001"],
        character_actions={"char_001": "walks through the woods"},
        character_positions={"char_001": "center"},
        background_description="Dense woods behind a farmhouse.",
        lighting="warm morning light",
        mood="playful safe",
    )
    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _story_bible())

    generation_prompt = render_generation_prompt(
        prompt,
        "Oil painting with broad expressive brushwork.",
    )

    assert "Style:\nOil painting with broad expressive brushwork." in generation_prompt
    assert "Visual brief:\nwide vertical panel" in generation_prompt
    assert "Myop, walks through the woods" in generation_prompt
    assert "Characters:\n" not in generation_prompt
    assert "Composition:\n" not in generation_prompt
    assert "Constraints:\n- exactly 1 character" in generation_prompt
    assert "Avoid stochastic grain" in generation_prompt
    assert "interpret it as broad intentional structure rather than all-over noise" in generation_prompt
    assert "Do not copy sample-image artifacts" in generation_prompt


def test_generation_prompt_prefers_distilled_prompt():
    prompt = ImagePrompt(
        scene_id="scene_004",
        panel_number=4,
        full_prompt="Composition: medium shot. Setting: library.",
        distilled_prompt="Medium shot inside the library, Ada crossing the lamplight.",
        composition="medium shot",
        setting="library",
        constraints="exactly 1 character; no text",
        width=768,
        height=1024,
        steps=28,
    )

    generation_prompt = render_generation_prompt(prompt, "Ink and watercolor.")

    assert "Visual brief:\nMedium shot inside the library" in generation_prompt
    assert "Composition:\nmedium shot" not in generation_prompt
    assert "Constraints:\n- exactly 1 character" in generation_prompt


def test_generate_distilled_prompt_keeps_visual_task_before_identity_anchor():
    prompt = ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        full_prompt="Ada, short black bob haircut, blue jacket. Composition: medium panel.",
        subjects=[
            PromptSubject(
                character_id="ada",
                name="Ada",
                identity="short black bob haircut, blue jacket",
                action="standing",
                expression="neutral",
                position="center frame",
            )
        ],
        composition="medium panel",
        setting="library",
        constraints="exactly 1 character; no text",
        width=768,
        height=1344,
        steps=8,
    )

    distilled = generate_distilled_prompt(prompt)

    assert distilled.startswith("medium panel of Ada, standing")
    assert "short black bob haircut, blue jacket" in distilled
    assert "library" in distilled


def test_generate_distilled_prompt_removes_caption_space_fragments():
    prompt = ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        composition=(
            "wide vertical panel, environment dominant, high angle camera, "
            "leave quiet negative space near the top for a narration caption added later"
        ),
        key_objects=["streetlamp", "apartment_building"],
        setting=(
            "night, outdoors, freezing, snow, ice, tree, sidewalk, streetlamp, "
            "7-story apartment building, winter storm, dark, cold lighting, urban, "
            "city street, residential, overcast; snowdrifts along the curb, wind-driven flakes"
        ),
        lighting="cold blue night with a single sodium streetlamp and faint warm window glow",
        mood="ominous",
        visual_requirements=[
            "Dark city street buried in snow at 2:23 AM",
            "Seven-story apartment building looming behind a bare tree",
        ],
        constraints="exactly 0 characters; no text",
        width=768,
        height=1344,
        steps=8,
    )

    distilled = generate_distilled_prompt(prompt)

    assert "leave quiet negative space" not in distilled
    assert "near the." not in distilled
    assert "apartment building" in distilled
    assert "apartment_building" not in distilled
    assert distilled.startswith(
        "wide vertical panel, environment dominant, high angle camera of streetlamp and apartment building."
    )


def test_generate_distilled_prompt_does_not_leave_dangling_shortened_clause():
    prompt = ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        composition=(
            "wide vertical panel, environment dominant, high angle camera, "
            "foreground framed with"
        ),
        setting="frozen residential street",
        constraints="exactly 0 characters; no text",
        width=768,
        height=1344,
        steps=8,
    )

    distilled = generate_distilled_prompt(prompt)

    assert "with." not in distilled
    assert distilled.startswith("wide vertical panel, environment dominant, high angle camera.")


def test_gpt_image_2_generation_prompt_adds_material_discipline():
    prompt = ImagePrompt(
        scene_id="scene_004",
        panel_number=4,
        composition="close-up detail shot, environment or object filling the panel",
        setting="leaf mold, dirt, rotted denim, corroded buckles, cracked bone",
        lighting="low diffuse woodland light",
        mood="macabre",
        visual_requirements=[
            "large white teeth are cracked",
            "last threads of faded blue denim cling to the skeleton",
            "two dull green corroded overall buckles rest on the ribcage",
        ],
        constraints="exactly 0 characters; no text",
        width=768,
        height=1024,
        steps=28,
    )

    gpt_prompt = render_generation_prompt(
        prompt,
        "Matte gouache, broad opaque shapes.",
        "image-quality",
    )
    gemini_prompt = render_generation_prompt(
        prompt,
        "Matte gouache, broad opaque shapes.",
        "image-balanced",
    )

    assert "Rendering discipline:\nGPT-image-2 material discipline" in gpt_prompt
    assert "do not cover surfaces with many similar flecks" in gpt_prompt
    assert "Keep quiet planes on bone, fabric, metal" in gpt_prompt
    assert "Rendering discipline:" not in gemini_prompt


def test_prompt_carries_key_objects_and_must_show_requirements(tmp_path):
    panel = PlannedPanel(
        panel_id="scene_002:panel_003",
        scene_id="scene_002",
        panel_number=3,
        beat_ids=["scene_002:beat_004"],
        shot_type="close-up",
        camera_angle="high angle",
        characters_present=["char_001"],
        character_actions={"char_001": "pinches the blue flowers between careful fingers"},
        character_expressions={"char_001": "mouth still, eyes fixed on the petals"},
        character_positions={"char_001": "center foreground"},
        key_objects=["Blue flowers"],
        visual_requirements=[
            "show the blue flowers pressed between her fingers",
            "show her mouth still and eyes fixed on the petals",
        ],
        background_description="forest floor falls out of focus behind her hands",
        lighting="thin sunlight through leaves",
        mood="hushed",
    )

    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _story_bible())
    generation_prompt = render_generation_prompt(prompt, "Ink wash, quiet naturalism.")

    assert "Key objects: Blue flowers" in prompt.full_prompt
    assert "Must show: show the blue flowers pressed between her fingers" in prompt.full_prompt
    assert "Blue flowers: small vivid blue flowers with velvety petals" in prompt.full_prompt
    assert "Visual brief:\nclose-up portrait" in generation_prompt
    assert "Blue flowers" in generation_prompt
    assert "show the blue flowers pressed between her fingers" in generation_prompt
    assert "Key objects:\n" not in generation_prompt
    assert "Key props:\n" not in generation_prompt


def test_rect_master_prompt_ignores_page_slot_aspect_for_image_shape(tmp_path):
    panel = PlannedPanel(
        panel_id="scene_002:panel_002",
        scene_id="scene_002",
        panel_number=2,
        shot_type="medium",
        shape_intent="rect",
        generation_mode="master",
        aspect_preference=0.3333333333333333,
        camera_angle="slightly elevated side view",
        characters_present=["char_001"],
        character_actions={"char_001": "walks beside the fence toward the stream"},
        character_positions={"char_001": "center"},
        background_description="Silver ferns and wild flowers crowd the water's edge.",
        lighting="bright natural daylight",
        mood="serene",
    )

    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _flowers_story_bible())

    assert dimensions_for_panel(panel) == (768, 1344)
    assert prompt.width == 768
    assert prompt.height == 1344
    assert "narrow vertical column" not in prompt.composition


def test_prompt_does_not_promote_ambient_flowers_to_carried_bundle_prop(tmp_path):
    prop_001_ref = tmp_path / "refs" / "props" / "prop_001" / "ref.png"
    prop_002_ref = tmp_path / "refs" / "props" / "prop_002" / "ref.png"
    prop_001_ref.parent.mkdir(parents=True)
    prop_002_ref.parent.mkdir(parents=True)
    prop_001_ref.write_bytes(b"stick")
    prop_002_ref.write_bytes(b"flowers")
    panel = PlannedPanel(
        panel_id="scene_002:panel_002",
        scene_id="scene_002",
        panel_number=2,
        shot_type="medium",
        characters_present=["char_001"],
        character_actions={"char_001": "walks beside the fence toward the stream"},
        character_positions={"char_001": "center"},
        key_objects=["prop_001", "prop_002", "Knobby Stick", "Bundle of Flowers"],
        visual_requirements=[
            "Silver ferns and wild flowers crowd the water's edge.",
            "Fence meeting the spring-fed stream.",
        ],
        background_description="Stream appears at the fence line; vegetation thickens.",
        lighting="bright natural daylight",
        mood="serene",
    )

    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _flowers_story_bible())
    generation_prompt = render_generation_prompt(prompt, "Seventeenth-century oil painting.")

    assert "Knobby Stick" in prompt.key_objects
    assert "prop_002" not in prompt.key_objects
    assert "Bundle of Flowers" not in prompt.key_objects
    assert "refs/props/prop_001/ref.png" in prompt.reference_image_paths
    assert "refs/props/prop_002/ref.png" not in prompt.reference_image_paths
    assert "Knobby Stick" in generation_prompt
    assert "Key props:\n" not in generation_prompt
    assert "Bundle of Flowers:" not in generation_prompt


def test_prompt_keeps_bundle_prop_when_character_carries_flowers(tmp_path):
    prop_002_ref = tmp_path / "refs" / "props" / "prop_002" / "ref.png"
    prop_002_ref.parent.mkdir(parents=True)
    prop_002_ref.write_bytes(b"flowers")
    panel = PlannedPanel(
        panel_id="scene_003:panel_003",
        scene_id="scene_002",
        panel_number=3,
        shot_type="medium",
        characters_present=["char_001"],
        character_actions={"char_001": "cradles an armful of wildflowers against her chest"},
        character_positions={"char_001": "center"},
        key_objects=["prop_002", "Bundle of Flowers"],
        visual_requirements=["A vivid armful of wildflowers pressed to her chest."],
        background_description="The forest recedes behind the blossoms.",
        lighting="filtered daylight",
        mood="wonder",
    )

    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _flowers_story_bible())

    assert "Bundle of Flowers" in prompt.key_objects
    assert "Bundle of Flowers: A large, messy armful" in prompt.full_prompt
    assert "refs/props/prop_002/ref.png" in prompt.reference_image_paths
