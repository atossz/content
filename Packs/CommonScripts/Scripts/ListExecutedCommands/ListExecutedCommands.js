var fixDate = function(date) {
    return date.Format('2006-01-02 15:04:05');
};

var entries = executeCommand('getEntries', {});

dbotCommands = [];
userCommands = [];
for (var i = 0; i < entries.length; i++) {
    if (typeof entries[i].Contents == 'string' && entries[i].Contents.indexOf('!') === 0 && entries[i].Contents.indexOf('!listExecutedCommands') !== 0) {
        if (entries[i].Metadata.User) {
            if (args.source === 'All' || args.source === 'Manual') {
                userCommands.push({
                    'Time': fixDate(entries[i].Metadata.Created),
                    'Entry ID': entries[i].ID,
                    'User': entries[i].Metadata.User,
                    'Command': entries[i].Contents
                });
            }
        } else {
            if (args.source === 'All' || args.source === 'Playbook') {
                dbotCommands.push({
                    'Time': fixDate(entries[i].Metadata.Created),
                    'Entry ID': entries[i].ID,
                    'Playbook (Task)': entries[i].Metadata.EntryTask.PlaybookName + " (" + entries[i].Metadata.EntryTask.TaskName + ")",
                    'Command': entries[i].Contents
                });
            }
        }
    }
}

var md = '';
if (dbotCommands.length > 0) {
    md += tableToMarkdown('DBot Executed Commands', dbotCommands, ['Time', 'Entry ID', 'Playbook (Task)', 'Command']) + '\n';
}
if (userCommands.length > 0) {
    md += tableToMarkdown('User Executed Commands', userCommands, ['Time', 'Entry ID', 'User', 'Command']) + '\n';
}
if (md === '') {
    md = 'No commands found\n';
}
return {ContentsFormat: formats.markdown, Type: entryTypes.note, Contents: md};
