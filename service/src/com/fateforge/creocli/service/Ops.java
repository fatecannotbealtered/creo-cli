package com.fateforge.creocli.service;

import java.util.Map;

/**
 * The operations the service runs, by name. There is no generic "run this" operation and
 * there will not be one: every op is a named, reviewed method. Names mirror the CLI
 * commands that call them.
 */
final class Ops {

    private Ops() {
    }

    static Map<String, Object> dispatch(String op, Map<String, Object> request) throws Exception {
        switch (op) {
            case "session.status": return SessionOps.status();
            case "session.cd": return SessionOps.cd(request);
            case "session.exit-state": return OwnedSessionExit.state(request);
            case "session.exit": throw new Failures.Refusal("E_VALIDATION", "owned exit requires the dedicated response-completion dispatch path");
            case "model.list": return ModelOps.list(request);
            case "model.management-state": return SessionOps.managementState();
            case "model.open": return ModelOps.open(request);
            case "model.save": return ModelOps.save(request);
            case "model.regenerate": return ModelOps.regenerate(request);
            case "model.close": return ModelOps.close(request, false);
            case "model.discard": return ModelOps.close(request, true);
            case "model.show": return ModelOps.show(request);
            case "model.definition-state": return DefinitionObservation.model(request);
            case "model.import": return ModelOps.importModel(request);
            case "relation.list": return Relations.list(request);
            case "relation.set": return Relations.set(request);
            case "part.create": return ModelOps.createPart(request);
            case "assembly.create": return Assemblies.create(request);
            case "assembly.add": return Assemblies.add(request);
            case "assembly.constraint-state": return AssemblyConstraints.state(request);
            case "assembly.redefine-constraints": return AssemblyConstraints.redefine(request);
            case "assembly.remove": return Assemblies.remove(request);
            case "assembly.replace": return Assemblies.replace(request);
            case "assembly.explode": return Assemblies.explode(request);
            case "assembly.check": return Assemblies.check(request);
            case "assembly.components": return Resources.components(request, false);
            case "assembly.placement": return Resources.components(request, true);
            case "assembly.exploded-states": return Resources.exploded(request);
            case "drawing.create": return Drawings.create(request);
            case "drawing.info": return Drawings.info(request);
            case "drawing.resources": return Drawings.resources(request);
            case "drawing.bom-template": return Detailing.bomTemplate(request);
            case "drawing.apply-layout": return Resources.applyLayout(request);
            case "drawing.activate": return Drawings.activate(request);
            case "drawing.lay-out": return Drawings.layOut(request);
            case "drawing.add-view": return Drawings.addView(request);
            case "drawing.move-view": return Views.move(request);
            case "drawing.annotate": return Drawings.annotate(request);
            case "drawing.hide-dimension": return Drawings.hideDimensions(request);
            case "drawing.add-note": return Drawings.addNote(request);
            case "drawing.edit-note": return Detailing.editNote(request);
            case "drawing.remove": return Detailing.remove(request);
            case "drawing.symbol": return Detailing.symbolDefinition(request);
            case "drawing.move-dimension": return Detailing.moveDimension(request);
            case "drawing.add-dimension": return Detailing.addDimension(request);
            case "drawing.add-table": return Detailing.addTable(request);
            case "drawing.add-bom": return Detailing.addBom(request);
            case "drawing.add-balloons": return Detailing.addBalloons(request);
            case "drawing.move-table": return Detailing.moveTable(request);
            case "drawing.add-symbol": return Detailing.addSymbol(request);
            case "drawing.add-datum": return Tolerances.addDatum(request);
            case "drawing.add-gtol": return Tolerances.addGtol(request);
            case "feature.list": return FeatureOps.list(request);
            case "feature.show": return FeatureOps.show(request);
            case "feature.extrude": return Extrude.create(request);
            case "feature.revolve": return Extrude.revolve(request);
            case "feature.datum-plane": return Features.datumPlane(request);
            case "feature.datum-axis": return Features.datumAxis(request);
            case "feature.round": return Features.round(request);
            case "feature.chamfer": return Features.chamfer(request);
            case "feature.hole": return Features.hole(request);
            case "feature.shell": return Features.shell(request);
            case "feature.draft": return Features.draft(request);
            case "hole.chart": return Holes.chart(request);
            case "feature.thread": return Holes.thread(request);
            case "feature.rib": return Ribs.rib(request);
            case "feature.sweep": return Sweeps.sweep(request);
            case "feature.pattern": return Features.pattern(request);
            case "feature.mirror": return Features.mirror(request);
            case "feature.delete": return FeatureOps.delete(request);
            case "feature.suppress": return FeatureOps.suppress(request);
            case "feature.resume": return FeatureOps.resume(request);
            case "feature.rename": return FeatureOps.rename(request);
            case "geometry.list": return Geometry.list(request);
            case "geometry.mass-properties": return Resources.geometry(request, false);
            case "geometry.bounds": return Resources.geometry(request, true);
            case "geometry.measure": return Geometry.measure(request);
            case "geometry.ray": return Geometry.ray(request);
            case "dimension.list": return Dimensions.list(request);
            case "dimension.set": return Dimensions.set(request);
            case "dimension.tolerance": return Dimensions.tolerance(request);
            case "model.set-tolerance-standard": return Dimensions.setToleranceStandard(request);
            case "model.set-common-name": return ModelOps.setCommonName(request);
            case "parameter.list": return ParameterOps.list(request);
            case "parameter.set": return ParameterOps.set(request);
            case "family.show": return Families.show(request);
            case "family.set": return Families.set(request);
            case "family.remove": return Families.remove(request);
            case "material.list": return Materials.list(request);
            case "material.assign": return Materials.assign(request);
            case "appearance.get": return AppearanceOps.get(request);
            case "appearance.set": return AppearanceOps.set(request);
            case "appearance.restore": return AppearanceOps.set(request);
            case "display.state": return PresentationOps.state(request);
            case "display.activate": return PresentationOps.activate(request);
            case "display.fit": return PresentationOps.fit(request);
            case "display.visibility": return PresentationOps.visibility(request);
            case "display.unexplode": return PresentationOps.unexplode(request);
            case "model.render": return Output.render(request);
            case "model.render-state": return Output.renderState(request);
            case "artifact.jpeg-inspect": return Output.inspectJpeg(request);
            case "model.export": return Output.export(request);
            default: throw new Failures.Refusal("E_VALIDATION", "unknown op '" + op + "'");
        }
    }
}
