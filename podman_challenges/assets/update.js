CTFd.plugin.run((_CTFd) => {
    const $ = _CTFd.lib.$
    const md = _CTFd.lib.markdown()
    $(document).ready(function() {
        $.getJSON("/api/v1/podman", function(result) {
            $.each(result['data'], function(i, item) {
                $("#podmanimage_select").append($("<option />").val(item.name).text(item.name));
            });
            $("#podmanimage_select").val(DOCKER_IMAGE).change();
        });
    });
});