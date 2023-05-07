CTFd.plugin.run((_CTFd) => {
    const $ = _CTFd.lib.$
    const md = _CTFd.lib.markdown()
    $('a[href="#new-desc-preview"]').on('shown.bs.tab', function (event) {
        if (event.target.hash == '#new-desc-preview') {
            var editor_value = $('#new-desc-editor').val();
            $(event.target.hash).html(
                md.render(editor_value)
            );
        }
    });
    $(document).ready(function(){
    $('[data-toggle="tooltip"]').tooltip();
    $.getJSON("/api/v1/podman", function(result){
        $.each(result['data'], function(i, item){
            if (item.name == 'Error in Podman Config!') { 
                document.podman_form.podmanimage_select.disabled = true;
                $("label[for='PodmanImage']").text('Podman Image ' + item.name)
            }
            else {
                $("#podmanimage_select").append($("<option />").val(item.name).text(item.name));
            }
        });
    });
});
});