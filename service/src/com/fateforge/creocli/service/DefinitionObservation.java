package com.fateforge.creocli.service;

import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.wfc.wfcFeature.WFeature;
import com.ptc.wfc.wfcFeature.FeatureElemTreeExtractOptions;
import com.ptc.wfc.wfcElementTree.ElementTree;
import com.ptc.wfc.wfcElementTree.ElementTreeFormat;
import java.lang.ref.Reference;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Node;

/** Independent, bounded native element-tree serialization for preservation checks.
 * This is not an interpretation of manufacturing intent. No setter reply is used.
 */
final class DefinitionObservation {
    private DefinitionObservation() { }

    static Map<String, Object> read(Feature feature) {
        ElementTree owner = null;
        Path temporary = null;
        boolean completed = false;
        try {
            Path directory = Service.stateDirectory().resolve("definition-observations");
            Files.createDirectories(directory);
            temporary = Files.createTempFile(directory, "read-", ".xml");
            owner = ((WFeature) feature).GetElementTree(null, FeatureElemTreeExtractOptions.FEAT_EXTRACT_NO_OPTS);
            if (owner == null) return Json.map("status", "unknown", "complete", false,
                    "reason", "native element tree is null");
            owner.WriteElementTreeToFile(ElementTreeFormat.ELEMTREE_XML, temporary.toString());
            long bytes = Files.size(temporary);
            if (bytes == 0 || bytes > 2097152) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "native definition XML size is outside 1..2 MiB");
            DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
            factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
            factory.setFeature("http://xml.org/sax/features/external-general-entities", false);
            factory.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
            factory.setXIncludeAware(false);
            factory.setExpandEntityReferences(false);
            Node root = factory.newDocumentBuilder().parse(temporary.toFile()).getDocumentElement();
            if (root == null || !root.hasChildNodes()) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "native definition XML is empty");
            StringBuilder canonical = new StringBuilder();
            canonical(root, canonical);
            byte[] value = canonical.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);
            String hash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value));
            Path evidence = directory.resolve(hash + ".xml");
            if (!Files.exists(evidence)) Files.copy(temporary, evidence);
            completed = true;
            return Json.map("status", "success", "complete", true, "sha256", hash,
                    "canonical_bytes", value.length, "source", "WFeature.GetElementTree.WriteElementTreeToFile/XML-v1",
                    "coverage", "entire serialized native element tree; no model geometry or manufacturing intent claim");
        } catch (Throwable failure) {
            Map<String, Object> error = Failures.error(failure);
            return Json.map("status", "E_UNSUPPORTED".equals(error.get("code")) ? "unsupported" : "failure",
                    "complete", false, "error", error, "source", "WFeature.GetElementTree.WriteElementTreeToFile/XML-v1",
                    "retained_scratch", temporary == null ? null : temporary.toString());
        } finally {
            Reference.reachabilityFence(owner);
            Reference.reachabilityFence(feature);
            // Only a freshly created task-owned scratch file is removed. Hash-named
            // successful XML evidence remains beside the service's own trace files.
            if (completed && temporary != null) try { Files.deleteIfExists(temporary); } catch (Exception ignored) { }
        }
    }

    private static void canonical(Node node, StringBuilder out) {
        out.append('[').append(node.getNodeType()).append(':').append(node.getNodeName().length()).append(':').append(node.getNodeName());
        if (node.hasAttributes()) {
            List<String> attributes = new ArrayList<>();
            for (int i = 0; i < node.getAttributes().getLength(); i++) {
                Node item = node.getAttributes().item(i);
                attributes.add(item.getNodeName() + "=" + item.getNodeValue());
            }
            java.util.Collections.sort(attributes);
            for (String attribute : attributes) out.append(attribute.length()).append(':').append(attribute);
        }
        if (node.getNodeValue() != null) out.append(node.getNodeValue().length()).append(':').append(node.getNodeValue());
        for (Node child = node.getFirstChild(); child != null; child = child.getNextSibling()) {
            if (child.getNodeType() == Node.TEXT_NODE && child.getNodeValue().isBlank() && node.hasChildNodes()
                    && node.getFirstChild() != node.getLastChild()) continue;
            canonical(child, out);
        }
        out.append(']');
    }

    static Map<String, Object> model(Map<String, Object> request) throws Exception {
        Solid solid = Creo.solid(Creo.session(), Json.string(request, "model"));
        com.ptc.pfc.pfcFeature.Features features = solid.ListFeaturesByType(Boolean.TRUE, null);
        if (features == null || features.getarraysize() > 256) throw new Failures.Refusal("E_UNSUPPORTED", "definition protection supports at most 256 visible features");
        List<Object> rows = new ArrayList<>();
        boolean complete = true;
        int excluded = 0;
        for (int i = 0; i < features.getarraysize(); i++) {
            Feature feature = features.get(i);
            // Component definitions are independently covered by complete constraint
            // and transform snapshots; source-part edits do not mutate placements.
            if ("FEATTYPE_COMPONENT".equals(Creo.enumName(feature.GetFeatType()))) { excluded++; continue; }
            Map<String, Object> definition = read(feature);
            complete &= Boolean.TRUE.equals(definition.get("complete"));
            rows.add(Json.map("id", Integer.toString(feature.GetId()), "type", Creo.enumName(feature.GetFeatType()),
                    "definition", definition));
        }
        return Json.map("model", Creo.fileName((Model) solid), "status", complete ? "success" : "failure",
                "complete", complete, "features", rows, "visible_feature_count", features.getarraysize(),
                "excluded_component_count", excluded, "scope", "visible non-component native element trees; components use constraint/transform protection");
    }
}
