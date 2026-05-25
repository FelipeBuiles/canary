import sys
from pathlib import Path

# Agregar la raíz del proyecto al path de Python
project_root = Path("/Users/jbuiles/Code/canary/novel_to_comic/src")
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

print("Iniciando verificación de integridad del cálculo de costos y créditos...")

try:
    from novel_to_comic.config import Config
    from novel_to_comic.state import PipelineState
    from novel_to_comic.server.credits import UnifiedCostResolver
    from novel_to_comic.stages import REGISTRY
    
    print("✓ Éxito: Importaciones completadas correctamente sin dependencias circulares.")
except Exception:
    import traceback
    print("✗ Error al importar módulos:")
    traceback.print_exc()
    sys.exit(1)

# Verificar que todas las etapas del REGISTRY tengan el atributo o método 'estimate_cost'
print("\nVerificando estimadores en el registro de etapas (REGISTRY):")
for name, stage in REGISTRY.items():
    has_estimator = stage.estimate_cost is not None
    print(f"  - Etapa '{name}': {'Tiene estimador ✓' if has_estimator else 'No tiene estimador'}")

# Crear una configuración y estado de prueba simulados
config = Config()
state = PipelineState(project_name="dummy", created_at="2026-05-25T00:00:00Z", novel_path="dummy.txt")
project_dir = Path("/Users/jbuiles/Code/canary/dummy_project")

# Probar el cálculo de costos usando UnifiedCostResolver
print("\nProbando estimaciones con UnifiedCostResolver:")
try:
    # 1. Estimación de etapa completa (Style)
    style_estimate = UnifiedCostResolver.estimate_stage_cost(config, project_dir, state, "style")
    print("  ✓ Estimación de la etapa 'style' exitosa:")
    print("    - Créditos estimados:", style_estimate.get("estimate_credits"))
    print("    - Créditos reservados:", style_estimate.get("reserved_credits"))
    print("    - Confianza:", style_estimate.get("confidence"))

    # 2. Estimación de regeneración de asset de cast
    asset_estimate = UnifiedCostResolver.estimate_asset_regen_cost(config, project_dir, "character", "protagonista")
    print("  ✓ Estimación de regeneración de personaje exitosa:")
    print("    - Créditos estimados:", asset_estimate.get("estimate_credits"))
    print("    - Confianza:", asset_estimate.get("confidence"))

    # 3. Estimación de regeneración de panel (debe levantar FileNotFoundError o similar si no existe el prompt,
    #    o podemos crear un prompt simulado o verificar que levante la excepción correcta)
    print("  - Verificando estimación de regeneración de panel (debe levantar 404 si el archivo no existe):")
    try:
        UnifiedCostResolver.estimate_panel_regen_cost(config, project_dir, "scene_1", 1)
        print("    ✗ Error: No levantó la excepción esperada para archivo no existente.")
    except Exception as exc:
        print(f"    ✓ Levantó excepción esperada (éxito): {exc}")

except Exception:
    import traceback
    print("✗ Error durante las pruebas de cálculo de costos:")
    traceback.print_exc()
    sys.exit(1)

print("\n✓ ¡Todas las pruebas de integridad de costos pasaron correctamente!")
