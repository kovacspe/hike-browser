var centerMap = SMap.Coords.fromWGS84(14.40, 50.08);
var m = new SMap(JAK.gel("m"), centerMap, 16);
var l = m.addDefaultLayer(SMap.DEF_BASE).enable();
m.addDefaultControls();


var nalezeno = function (route) {
    var vrstva = new SMap.Layer.Geometry();
    m.addLayer(vrstva).enable();

    var coords = route.getResults().geometry;
    var cz = m.computeCenterZoom(coords);
    m.setCenterZoom(cz[0], cz[1]);
    var g = new SMap.Geometry(SMap.GEOMETRY_POLYLINE, null, coords);
    vrstva.addGeometry(g);
}

var coords = [
    SMap.Coords.fromWGS84(14.434, 50.084),
    SMap.Coords.fromWGS84(16.600, 49.195)
];