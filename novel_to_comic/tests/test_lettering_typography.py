"""Real-font/browser evidence for typography, not evidence of image-model quality."""

import io
import json
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright
from pydantic import ValidationError

from novel_to_comic.lettering.renderer import (
    _fonts,
    _source,
    render_lettered_page,
    resolve_lettering,
)
from novel_to_comic.lettering.service import preset_style
from novel_to_comic.models.lettering import (
    LetteringElement,
    PageLettering,
    ResolvedLineMetrics,
)


@pytest.fixture(scope="module")
def typography():
    style = preset_style()
    cases = [
        ("short", "speech", "Yes? What is your business, sir?", (.07, .06, .32, .11)),
        ("long", "speech", "My name is Henry. I am the nephew of the late professor. He asked me to bring you these letters before I leave.", (.50, .20, .33, .15)),
        ("caption", "caption", "The house stood at the end of a narrow street. Its windows caught the last light of the afternoon, but the room beyond them was already dark. I had come with a letter and a question.", (.07, .43, .43, .20)),
    ]
    elements = []
    for name, role, text, values in cases:
        rect = dict(zip(("x", "y", "width", "height"), values))
        elements.append(LetteringElement(
            id=name, role=role, text_by_locale={"source": text},
            suggested_placement=rect, placement=rect,
            tail_target={"x": .455, "y": .29} if name == "long" else None,
        ))
    state = PageLettering(
        revision=1, page_number=1, comic_page_sha256="a" * 64,
        style_sha256=style.content_sha256, canvas_aspect_ratio=1000 / 1350,
        elements=elements,
    )
    return state, style


@pytest.fixture(scope="module")
def browser_page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1000, "height": 1350})
        page.route("**/*", lambda route: route.abort())
        page.set_content('<style>' + _fonts() + '</style><div id="out"></div>')
        page.add_script_tag(type="module", content=_source() + "\nwindow.engine={resolvePage,renderOverlay,canvasMeasure,loadFonts};")
        page.wait_for_function("window.engine")
        page.evaluate("window.engine.loadFonts()")
        yield page
        browser.close()


def test_real_glyph_layout_matches_server_and_fits_the_drawn_contour(typography, browser_page):
    state, style = typography
    server = resolve_lettering(state, style)
    value = browser_page.evaluate("""({state,style})=>{
      const e=window.engine, measure=e.canvasMeasure();
      const resolved=e.resolvePage(state,style,measure);
      document.getElementById('out').innerHTML=e.renderOverlay(resolved,style);
      const defects=[];
      for(const element of resolved.elements){
        const body=document.querySelector(`[data-lettering-id="${element.id}"] [data-balloon-body]`);
        for(const [i,m] of element.resolved.line_metrics.entries()){
          // Bounding ink corners must be inside the exact SVG path, not merely
          // inside the element rectangle. The production fit also adds padding.
          for(const x of [m.x,m.x+m.width]) for(const y of [m.baseline-m.ascent,m.baseline+m.descent])
            if(!body.isPointInFill(new DOMPoint(x,y))) defects.push({id:element.id,line:i});
        }
      }
      return {resolved,defects};
    }""", {"state": state.model_dump(mode="json"), "style": style.model_dump(mode="json")})
    assert not value["defects"]
    for actual, expected in zip(value["resolved"]["elements"], server.elements):
        assert actual["resolved"] == expected.resolved.model_dump(mode="json")
        assert not expected.resolved.overflow
    short, long, caption = server.elements
    assert short.resolved.lines == ("Yes? What is", "your business, sir?")
    assert 150 < short.resolved.width * 1000 < 180
    assert 60 < short.resolved.height * 1350 < 80
    assert len(long.resolved.lines) == 4
    assert long.resolved.width * 1000 > long.resolved.height * 1350 * 2
    assert caption.resolved.height < caption.placement.height


@pytest.mark.parametrize("shape,seed", [("ellipse", "oval"), *[("cloud", f"cloud-{i}") for i in range(6)]])
def test_curved_shapes_contain_padded_ink_through_every_row_band(typography, browser_page, shape, seed):
    state, style = typography
    value = browser_page.evaluate("""({state,style,shape,seed})=>{
      const e=window.engine, measure=e.canvasMeasure(), defects=[];
      for(const role of ['caption','speech','thought']) for(const tight of [true,false])
      for(const align of ['left','center','right']) {
        const draft=structuredClone(state); draft.elements=[draft.elements[1]];
        const element=draft.elements[0];
        element.id=seed; element.role=role; element.tight_box=tight; element.tail_target=null;
        element.style_override={...style.roles.speech,shape,align};
        const resolved=e.resolvePage(draft,style,measure), r=resolved.elements[0].resolved;
        document.getElementById('out').innerHTML=e.renderOverlay(resolved,style);
        const body=document.querySelector('[data-balloon-body]');
        const s=element.style_override, padding=s.padding+s.stroke_width/2+s.text_stroke_width/2;
        if(r.overflow || r.font_size<s.min_font_size) defects.push({role,tight,align,reason:'fit'});
        for(const [line,m] of r.line_metrics.entries()) {
          const top=m.baseline-m.ascent-padding, bottom=m.baseline+m.descent+padding;
          // Concave cloud valleys can cross a row between its four corners.
          // Check the whole padded rectangle, not the old inset-ellipse proxy.
          for(let y=top+.01;y<bottom;y+=.5)
          for(const x of [m.x-padding+.01,m.x+m.width+padding-.01])
            if(!body.isPointInFill(new DOMPoint(x,y))) defects.push({role,tight,align,line,x,y});
        }
      }
      return defects;
    }""", {"state": state.model_dump(mode="json"), "style": style.model_dump(mode="json"), "shape": shape, "seed": seed})
    assert value == []


def test_tail_is_part_of_one_contour_in_all_directions_and_transforms(typography, browser_page):
    state, style = typography
    value = browser_page.evaluate("""({state,style})=>{
      const e=window.engine, measure=e.canvasMeasure(), defects=[];
      let cases=0;
      for(const shape of ['balloon','ellipse','cloud','box','round'])
      for(const rotation of [0,35,-60]) for(const scale of [.8,1,1.4])
      for(let i=0;i<8;i++) {
        const draft=structuredClone(state); draft.elements=[draft.elements[0]];
        const element=draft.elements[0];
        element.tight_box=false; element.placement={x:.35,y:.35,width:.3,height:.16};
        element.rotation=rotation; element.scale=scale;
        element.style_override={...style.roles.speech,shape,fill:'transparent'};
        element.tail_target={x:.5+.34*Math.cos(i*Math.PI/4),y:.43+.3*Math.sin(i*Math.PI/4)};
        const resolved=e.resolvePage(draft,style,measure),svg=e.renderOverlay(resolved,style);
        document.getElementById('out').innerHTML=svg;
        const paths=document.querySelectorAll('[data-balloon-body]');
        if(paths.length!==1 || /NaN|Infinity|undefined/.test(svg)) defects.push({shape,rotation,scale,i});
        const r=resolved.elements[0].resolved, h=r.height*1350, w=r.width*1000;
        const wx=element.tail_target.x*1000-(350+w/2),wy=element.tail_target.y*1350-(.35*1350+h/2);
        const a=-rotation*Math.PI/180;
        const target=[w/2+(wx*Math.cos(a)-wy*Math.sin(a))/scale,h/2+(wx*Math.sin(a)+wy*Math.cos(a))/scale];
        const serialized=target.map(n=>Number(n.toFixed(4))).join(',');
        if(!paths[0].getAttribute('d').includes(serialized)) defects.push({shape,rotation,scale,i,reason:'tip moved'});
        cases++;
      }
      return {cases,defects};
    }""", {"state": state.model_dump(mode="json"), "style": style.model_dump(mode="json")})
    assert value["cases"] == 360
    assert value["defects"] == []


def test_versioned_layout_is_required_before_export_and_composes_real_pixels(typography):
    state, style = typography
    resolved = resolve_lettering(state, style)
    buffer = io.BytesIO()
    Image.new("RGB", (1000, 1350), "#5e6768").save(buffer, format="PNG")
    image = buffer.getvalue()
    data = render_lettered_page(resolved, style, image, 1000, 1350)
    with Image.open(io.BytesIO(data)) as output:
        assert output.size == (1000, 1350)
        assert output.getpixel((100, 100)) != (94, 103, 104)
    old = resolved.model_dump(mode="json")
    old["content_sha256"] = ""
    for element in old["elements"]:
        element["resolved"]["engine_version"] = "lettering-svg-v1"
        element["resolved"].pop("width")
        element["resolved"].pop("line_metrics")
    retained = PageLettering.model_validate(old)
    with pytest.raises(ValueError, match="Open Lettering and save"):
        render_lettered_page(retained, style, image, 1000, 1350)


@pytest.mark.parametrize("number", [float("inf"), float("nan"), -float("inf")])
def test_saved_ink_positions_reject_nonfinite_values(number):
    with pytest.raises(ValidationError):
        ResolvedLineMetrics(x=0, baseline=number, width=12, ascent=9, descent=3)


def test_fixture_and_literary_preset_use_the_same_role_defaults():
    fixture = json.loads((Path(__file__).resolve().parents[2] / "web/src/__tests__/fixtures/lettering.json").read_text())
    style = preset_style()
    assert fixture["style"] == style.model_dump(mode="json")
    assert style.roles.speech.font == style.roles.caption.font == "EB Garamond"
    assert style.roles.speech.shape == "balloon"
    assert preset_style("classic").roles.speech.font == "Comic Neue"


def test_bundled_font_coverage_table_matches_the_actual_font_files():
    """Changing a font must deliberately regenerate client/server glyph coverage."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    subprocess.run([sys.executable, str(root / "scripts/update_lettering_fonts.py"), "--check"], check=True)


@pytest.mark.parametrize("font", ["Comic Neue", "M PLUS 1p", "Fredoka"])
def test_thought_sample_balances_lines_and_renders_the_measured_font(typography, browser_page, font):
    state, style = typography
    value = browser_page.evaluate("""({state,style,font})=>{
      const e=window.engine, draft=structuredClone(state);
      draft.elements=[draft.elements[0]];
      const element=draft.elements[0];
      element.role='thought'; element.tail_target=null;
      element.text_by_locale={source:'Did you hear that?'};
      element.placement={x:.05,y:.53,width:.44,height:.16};
      element.style_override={...style.roles.thought,font,shape:'cloud',align:'center',
        padding:6,min_font_size:22,max_font_size:22,letter_spacing:0};
      const resolved=e.resolvePage(draft,style,e.canvasMeasure());
      document.getElementById('out').innerHTML=e.renderOverlay(resolved,style);
      const r=resolved.elements[0].resolved;
      const texts=[...document.querySelectorAll('text')];
      return {lines:r.lines, ratio:r.width*1000/Math.max(...r.line_metrics.map(m=>m.width)),
        families:texts.map(t=>getComputedStyle(t).fontFamily.replaceAll('"','')),
        widths:texts.map(t=>t.getComputedTextLength()), metrics:r.line_metrics.map(m=>m.width)};
    }""", {"state": state.model_dump(mode="json"), "style": style.model_dump(mode="json"), "font": font})
    assert value["lines"] == ["Did you", "hear that?"]
    assert value["ratio"] < 1.45
    assert value["families"] == [font, font]
    assert value["widths"] == pytest.approx(value["metrics"], abs=1)
