function add_point_of_interest(map, point) {
    var marker = L.marker(["{{ point.lat }}", "{{ point.lon }}"], {
        icon: L.divIcon({
            className: 'material-icons',
            html: `<span class="material-icons">{{point.type.icon}}</span>`
        })
    });
    marker.addTo(map);
    marker.bindPopup("<b>{{point.name}}</b><br>{{point.description}}")
}