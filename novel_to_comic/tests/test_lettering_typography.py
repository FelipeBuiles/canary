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
    ResolvedLettering,
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
        # Match the export renderer's 1:1 canvas/SVG scale. Default body margins
        # shrink the SVG to 984px; Linux font hinting then changes text advances.
        page.set_content('<style>' + _fonts() + '</style>'
                         '<style>html,body{margin:0;padding:0}</style><div id="out"></div>')
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
        assert ResolvedLettering.model_validate(actual["resolved"]) == expected.resolved
        assert not expected.resolved.overflow
    short, long, caption = server.elements
    assert short.resolved.lines == ("Yes? What is", "your business, sir?")
    assert 150 < short.resolved.width * 1000 < 180
    assert 60 < short.resolved.height * 1350 < 80
    assert len(long.resolved.lines) == 4
    assert long.resolved.width * 1000 > long.resolved.height * 1350 * 2
    assert caption.resolved.height < caption.placement.height


@pytest.mark.parametrize("shape,seed", [
    ("ellipse", "oval"), *[("cloud", f"cloud-{i}") for i in range(6)],
    *[("burst", f"burst-{i}") for i in range(4)],
])
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
      for(const shape of ['balloon','ellipse','cloud','box','round','burst','wavy','electric','whisper'])
      for(const rotation of [0,35,-60]) for(const scale of [.8,1,1.4])
      for(let i=0;i<8;i++) {
        const draft=structuredClone(state); draft.elements=[draft.elements[0]];
        const element=draft.elements[0];
        element.tight_box=false; element.placement={x:.35,y:.35,width:.3,height:.16};
        element.rotation=rotation; element.scale=scale; element.tail_bend=[0,.7,-.45][i%3];
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
    assert value["cases"] == 648
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
        scale:document.querySelector('svg').getScreenCTM().a,
        widths:texts.map(t=>t.getComputedTextLength()), metrics:r.line_metrics.map(m=>m.width)};
    }""", {"state": state.model_dump(mode="json"), "style": style.model_dump(mode="json"), "font": font})
    assert value["lines"] == ["Did you", "hear that?"]
    assert value["ratio"] < 1.45
    assert value["families"] == [font, font]
    assert value["scale"] == pytest.approx(1)
    assert value["widths"] == pytest.approx(value["metrics"], abs=1)


def test_burst_valleys_stay_outside_the_fitted_ellipse(browser_page):
    """Burst rows fit inside a 0.78 ellipse; no seeded spike valley may cut it."""
    defects = browser_page.evaluate("""()=>{
      const e=window.engine, measure=e.canvasMeasure(), defects=[];
      const style={revision:1,content_sha256:'s',label:'x',source_direction:'',roles:{}};
      for(const [w,h] of [[.3,.12],[.2,.2],[.5,.1],[.12,.3]]) for(let i=0;i<12;i++) {
        const role={font:'Comic Neue',font_weight:400,min_font_size:12,max_font_size:14,line_height:1,align:'center',
          color:'#181818',fill:'#ffffff',stroke:'#181818',stroke_width:0,padding:0,corner_radius:0,shape:'burst',
          letter_spacing:0,text_stroke:'transparent',text_stroke_width:0};
        const rect={x:.1,y:.1,width:w,height:h};
        const state={revision:1,content_sha256:'',page_number:1,comic_page_sha256:'0'.repeat(64),style_sha256:'s',
          locale:'source',canvas_aspect_ratio:1,reviewed_against_render_revision:null,reviewed_against_image_sha256:null,
          elements:[{id:'burst-'+i,source_lettering_item_id:null,role:'caption',text_by_locale:{source:'A'},
            suggested_placement:rect,placement:rect,hidden:false,style_override:role,tail_target:null,
            suggested_tail_target:null,rotation:0,scale:1,z_index:0,tight_box:false,resolved:null}]};
        const resolved=e.resolvePage(state,style,measure);
        document.getElementById('out').innerHTML=e.renderOverlay(resolved,style);
        const body=document.querySelector('[data-balloon-body]');
        const cx=(rect.x+w/2)*1000, cy=(rect.y+h/2)*1000;
        for(let a=0;a<360;a+=2) {
          const x=cx+Math.cos(a*Math.PI/180)*w*500*.78, y=cy+Math.sin(a*Math.PI/180)*h*500*.78;
          if(!body.isPointInFill(new DOMPoint(x-rect.x*1000,y-rect.y*1000))) { defects.push({w,h,i,a}); break; }
        }
      }
      return defects;
    }""")
    assert defects == []


def test_emphasis_and_capitals_lay_out_identically_in_the_server_and_stay_inside(typography, browser_page):
    state, style = typography
    styled = style.model_copy(update={"roles": style.roles.model_copy(update={
        "speech": style.roles.speech.model_copy(update={"text_case": "upper", "font": "Comic Neue"}),
    })})
    draft = state.model_copy(update={"style_sha256": styled.content_sha256, "elements": tuple(
        element.model_copy(update={"text_by_locale": {"source": "You *really* think we can get out of here *alive*? \\*Honestly*"}})
        if element.id == "short" else element for element in state.elements
    )})
    server = resolve_lettering(draft, styled)
    short = next(element for element in server.elements if element.id == "short")
    assert short.resolved.text.startswith("You *really*")
    assert "\ue000REALLY\ue000" in " ".join(short.resolved.lines)
    assert "*HONESTLY*" in " ".join(short.resolved.lines)
    value = browser_page.evaluate("""({state,style})=>{
      const e=window.engine, resolved=e.resolvePage(state,style,e.canvasMeasure());
      document.getElementById('out').innerHTML=e.renderOverlay(resolved,style);
      const element=resolved.elements.find(item=>item.id==='short'), defects=[];
      const body=document.querySelector('[data-lettering-id="short"] [data-balloon-body]');
      for(const m of element.resolved.line_metrics) for(const x of [m.x,m.x+m.width]) for(const y of [m.baseline-m.ascent,m.baseline+m.descent])
        if(!body.isPointInFill(new DOMPoint(x,y))) defects.push({x,y});
      return {resolved:element.resolved,defects,italic:document.querySelectorAll('[data-lettering-id="short"] tspan[font-style="italic"]').length};
    }""", {"state": draft.model_dump(mode="json"), "style": styled.model_dump(mode="json")})
    assert value["defects"] == []
    assert value["italic"] == 2
    assert ResolvedLettering.model_validate(value["resolved"]) == short.resolved


def test_linked_balloons_merge_into_one_silhouette(typography, browser_page):
    state, style = typography
    first = LetteringElement(id="first", role="speech", text_by_locale={"source": "Wait."},
        placement={"x": .2, "y": .2, "width": .25, "height": .1}, suggested_placement={"x": .2, "y": .2, "width": .25, "height": .1})
    second = LetteringElement(id="second", role="speech", text_by_locale={"source": "Listen."}, link_to="first",
        placement={"x": .38, "y": .3, "width": .25, "height": .1}, suggested_placement={"x": .38, "y": .3, "width": .25, "height": .1})
    draft = state.model_copy(update={"elements": (first, second)})
    resolved = resolve_lettering(draft, style)
    value = browser_page.evaluate("""({state,style})=>{
      const e=window.engine;
      document.getElementById('out').innerHTML=e.renderOverlay(state,style);
      const group=document.querySelector('[data-lettering-link]'), bridge=document.querySelector('[data-balloon-bridge]');
      const boxes=state.elements.map(item=>{const r=item.resolved,p=item.placement;return [p.x*1000+r.width*500,p.y*1350+r.height*675];});
      const mid=[(boxes[0][0]+boxes[1][0])/2,(boxes[0][1]+boxes[1][1])/2];
      return {group:!!group, texts:group?.querySelectorAll('[data-lettering-id]').length, bridged:!!bridge && bridge.isPointInStroke!==undefined,
        inside:[...document.querySelectorAll('path')].some(path=>path.getAttribute('stroke')==='none' && path.isPointInFill(new DOMPoint(...mid)))};
    }""", {"state": resolved.model_dump(mode="json"), "style": style.model_dump(mode="json")})
    assert value == {"group": True, "texts": 2, "bridged": True, "inside": True}


@pytest.mark.parametrize("links", [{"a": "a"}, {"a": "missing"}, {"a": "b", "b": "a"}])
def test_balloon_links_reject_self_missing_and_loops(links):
    geometry = {"x": .1, "y": .1, "width": .2, "height": .1}
    elements = [LetteringElement(id=name, role="speech", text_by_locale={"source": name}, placement=geometry,
        suggested_placement=geometry, link_to=links.get(name)) for name in ("a", "b")]
    with pytest.raises(ValidationError, match="balloon links"):
        PageLettering(revision=1, page_number=1, comic_page_sha256="a" * 64, style_sha256="b" * 64,
            canvas_aspect_ratio=.75, elements=elements)


@pytest.mark.parametrize("shape", ["balloon", "whisper", "wavy", "electric"])
def test_balloon_family_contains_its_ink_inside_ripples_and_teeth(typography, browser_page, shape):
    """Balloon-derived bodies fit bare ink plus clearance, not padded bands."""
    state, style = typography
    value = browser_page.evaluate("""({state,style,shape})=>{
      const e=window.engine, measure=e.canvasMeasure(), defects=[];
      for(const role of ['caption','speech','thought']) for(const tight of [true,false])
      for(const align of ['left','center','right']) for(const seed of ['a','b','c']) {
        const draft=structuredClone(state); draft.elements=[draft.elements[1]];
        const element=draft.elements[0];
        element.id=shape+seed; element.role=role; element.tight_box=tight; element.tail_target=null;
        element.style_override={...style.roles.speech,shape,align};
        const resolved=e.resolvePage(draft,style,measure), r=resolved.elements[0].resolved;
        document.getElementById('out').innerHTML=e.renderOverlay(resolved,style);
        const body=document.querySelector('[data-balloon-body]'), inset=element.style_override.stroke_width/2;
        if(r.overflow) defects.push({role,tight,align,seed,reason:'fit'});
        for(const [line,m] of r.line_metrics.entries())
          for(let y=m.baseline-m.ascent-inset+.01;y<m.baseline+m.descent+inset;y+=.5)
          for(const x of [m.x-inset+.01,m.x+m.width+inset-.01])
            if(!body.isPointInFill(new DOMPoint(x,y))) defects.push({role,tight,align,seed,line,x,y});
      }
      return defects;
    }""", {"state": state.model_dump(mode="json"), "style": style.model_dump(mode="json"), "shape": shape})
    assert value == []
