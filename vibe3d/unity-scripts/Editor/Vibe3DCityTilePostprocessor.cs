using UnityEngine;
using UnityEditor;

/// <summary>
/// Vibe3D Drone2Twin — auto-configure OBJ city tile import settings.
/// Runs when OBJ assets are imported into Assets/CityTiles/.
/// </summary>
public class Vibe3DCityTilePostprocessor : AssetPostprocessor
{
    void OnPreprocessModel()
    {
        if (!assetPath.StartsWith("Assets/CityTiles/"))
            return;

        ModelImporter importer = assetImporter as ModelImporter;
        if (importer == null) return;

        // Scale: 1:1 meters, use file units
        importer.globalScale = 1f;
        importer.useFileUnits = true;

        // Normals: calculate
        importer.importNormals = ModelImporterNormals.Calculate;
        importer.normalCalculationMode = ModelImporterNormalCalculationMode.AreaAndAngleWeighted;

        // Mesh compression for large city tiles
        importer.meshCompression = ModelImporterMeshCompression.Medium;

        // No animation for static city tiles
        importer.importAnimation = false;
        importer.animationType = ModelImporterAnimationType.None;

        // Memory: readable for LOD generation (CityTileLODGenerator needs vertex data)
        importer.isReadable = true;

        // Material: import via material description (auto MTL recognition)
        importer.materialImportMode = ModelImporterMaterialImportMode.ImportViaMaterialDescription;

        Debug.Log($"[Vibe3D] CityTile postprocessor applied to: {assetPath}");
    }

    void OnPreprocessTexture()
    {
        if (!assetPath.StartsWith("Assets/CityTiles/"))
            return;

        TextureImporter importer = assetImporter as TextureImporter;
        if (importer == null) return;

        // City tiles: 4096 max for quality aerial textures
        importer.maxTextureSize = 4096;

        // High quality compression
        importer.textureCompression = TextureImporterCompression.CompressedHQ;

        // Mipmaps for distance rendering
        importer.mipmapEnabled = true;

        Debug.Log($"[Vibe3D] CityTile texture postprocessor applied to: {assetPath}");
    }
}
