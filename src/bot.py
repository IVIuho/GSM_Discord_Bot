import asyncio
import discord
import json
import operator
import os
import re
import time
import warnings
import youtube_dl
from datetime import datetime
from functools import partial

from const import Strings
from web_crawler import DataManager, TimeCalculator


def public_only(original_func):
    async def wrapper(self, message):
        if isinstance(message.channel, discord.abc.PrivateChannel):
            await message.channel.send(Strings.PRIVATE_SUPPORT)
            return
        else:
            return await original_func(self, message)
    wrapper.__doc__ = original_func.__doc__
    return wrapper


def admin_only(original_func):
    async def wrapper(self, message):
        if message.author.id not in self.admin:
            await message.channel.send(Strings.ADMIN_ONLY)
            return
        else:
            return await original_func(self, message)
    wrapper.__doc__ = original_func.__doc__
    return wrapper


def mapping_state_to_message(status):
    if status == discord.Status.online:
        return Strings.ONLINE
    elif status == discord.Status.offline:
        return Strings.OFFLINE
    elif status == discord.Status.idle:
        return Strings.IDLE
    elif status == discord.Status.do_not_disturb:
        return Strings.DO_NOT_DISTURB


def get_nickname(member):
    if member.nick:
        return member.nick
    else:
        return member.name


def get_peeklist_to_string(dic):
    string = str()
    for i in dic.keys():
        string += (str(i) + " ")
    return "%s : %s" % (Strings.PEEK_LIST, string)

weekend_string = Strings.WEEKEND_STRINGS


class Timer:
    def start(self):
        self.start_time = time.time()

    def end(self):
        delta_time = time.time() - self.start_time
        return (
            delta_time / 3600,
            (delta_time / 60) % 60,
            delta_time % 60
        )


class GSMBot(discord.Client):
    def __init__(self, *, admin, debug=False):
        self.admin = (admin, )
        self.debug = debug

        if not os.path.exists(os.path.join("..", "keyword")):
            print("[Setup] Created keyword directory")
            os.makedirs("keyword")

        if not os.path.exists(os.path.join("..", "vote")):
            print("[Setup] Created vote directory")
            os.makedirs("vote")

        self.prefix = "gsm"
        self.color = 0x7ACDF4
        self.commands = tuple([i.split("command_")[-1] for i in list(
                filter(lambda param: param.startswith("command_"), dir(self))
            )]
        )

        # GSM Bot의 모든 요소를 불러온 후, command_로 시작하는 함수들만 리스트로 만들어서 출력
        # command_x에서 _를 기준으로 맨 뒤, 즉 x만 msg에 추가한다
        self.commandDocs = "".join(["***%s***\n%s\n" %
            (i.split("_")[-1], (getattr(self, "command_%s" % i).__doc__).strip()) for i in self.commands])

        self.peekList = {}
        self.serverCount = {}
        self.appInfo = None
        self.DESCRIPTION_MESSAGE = "이것은 [GSM](https://www.gsm.hs.kr/)의 학생들을 위해서 만들어진 학교 전용 봇입니다.\n" +\
            "그렇기 때문에 오직 [GSM](https://www.gsm.hs.kr/) 학생들을 위한 편의기능만 제공하고 있습니다.\n"

        super().__init__()

    async def on_ready(self):
        activity_name = Strings.DEBUGGING if self.debug else Strings.COMMAND_HELP
        activity = discord.Activity(name=activity_name, type=discord.ActivityType.listening)
        await self.change_presence(activity=activity)
        print("GSM Bot 준비 완료!", end="\n\n")

    async def on_message(self, message):
        await self.wait_until_ready()

        if not message.author.bot:
            if isinstance(message.channel, discord.abc.GuildChannel):
                await self.message_log(message)

            command = message.content.lower()  # 명령어가 대문자로 들어와도 인식할 수 있게 모두 소문자로 변환
            if not command.startswith(self.prefix):  # 명령어를 입력한게 아니라면 바로 함수 종료
                return

            if self.debug and message.author.id not in self.admin:
                await message.channel.send(Strings.NOW_DEBUGGING)
                return

            # gsm hungry를 입력했다면, 공백을 기준으로 스플릿한 마지막 결과, 즉 hungry가 command 변수에 들어가게 됨
            command = command.split()[-1]
            func = getattr(self, "command_%s" % command, None)
            # GSMBot 클래스에 해당 명령어가 있으면 func에 함수를 저장함
            # 해당 명령어가 존재하지 않는다면 None을 반환한다.

            try:  # 디스코드 닉네임이 인식할 수 없는 문자인 경우에 UnicodeEncodeError가 발생하므로 예외처리
                today = datetime.now()
                print("[%02d:%02d] %s : %s"
                    % (today.hour, today.minute, message.author, command))
            except UnicodeEncodeError:
                pass

            if func:
                await func(message)  # 저장했던 함수 실행
            else:  # 함수가 없어서 None이 반환됐을 때
                print("[오류] %s는 명령어가 아닙니다. (User : %s)" %
                    (command, message.author))
                return

    async def on_member_update(self, before, after):
        await self.wait_until_ready()

        if before not in self.peekList.keys():  # 감시 리스트에 있지 않으면 바로 리턴
            return

        if not before.roles == after.roles:
            return

        msg, em, limit = None, None, 0

        for i in self.guilds:
            if before in i.members:
                limit += 1

        self.serverCount[before] += 1

        if not before.activity == after.activity:
            msg = "%s님이 %s을 시작하셨습니다." % (
                before.name, (lambda activity: activity.name if activity else "휴식")(after.activity))

        if not before.status == after.status:
            msg = "%s님이 %s에서 %s로 상태를 바꿨습니다." % (
                before.name, mapping_state_to_message(before.status), mapping_state_to_message(after.status))

        if not before.avatar == after.avatar:
            em = discord.Embed(title="%s님이 프로필 사진을 바꾸셨습니다" %
                               before.name, colour=self.color)
            em.set_image(url=(
                lambda member: member.avatar_url if member.avatar else member.default_avatar_url)(after))

        if not before.nick == after.nick:
            msg = "%s님이 %s에서 %s로 닉네임을 변경하셨습니다." % (
                before, get_nickname(before), get_nickname(after))
            limit = 1

        if self.serverCount[before] == limit:
            self.serverCount[before] = 0
            for i in self.peekList[before]:
                try:
                    await i.send(msg, embed=em)
                except:
                    print(msg, em)

    async def command_gsm(self, message):
        """
        GSM Bot의 명령어를 모두 출력합니다.
        """
        await message.channel.trigger_typing()

        em = discord.Embed(title="**GSM Bot**",
                           description=self.DESCRIPTION_MESSAGE, colour=0x7ACDF4)
        em.add_field(name="**GSM Bot의 명령어**", value=self.commandDocs)
        em.set_thumbnail(url=Strings.GSM_LOGO)
        await message.channel.send(embed=em)

    @admin_only
    async def command_logout(self, message):
        """
        GSM Bot을 종료시킵니다.
        """
        await message.channel.send(Strings.GSM_BOT_DIE)
        await self.logout()

    async def command_hungry(self, message):
        """
        GSM의 다음 식단표를 알려줍니다.
        8:00, 13:30, 19:30을 기준으로 표시하는 식단표가 바뀝니다.
        """
        await message.channel.trigger_typing()

        today = TimeCalculator.get_next_day()
        title = "%s년 %s월 %s일 %s의 %s 식단표" % (
            today.year, today.month, today.day,
            weekend_string[int(today.weekday())],
            ["아침", "점심", "저녁"][TimeCalculator.get_next_meal_index(today) % 3]
        )
        em = discord.Embed(
            title=title,
            description=DataManager.get_command("hungry"),
            colour=self.color
        )
        await message.channel.send(embed=em)

    async def command_calendar(self, message):
        """
        GSM의 한 달간의 학사일정을 알려줍니다.
        """
        await message.channel.trigger_typing()
        today = datetime.now()
        title = "%s년 %s월의 학사일정" % (today.year, today.month)
        em = discord.Embed(
            title=title,
            description=DataManager.get_command("calendar"),
            colour=self.color
        )
        await message.channel.send(embed=em)

    async def command_invite(self, message):
        """
        GSM Bot을 초대하기 위한 링크를 받습니다.
        """
        if not self.appInfo:
            self.appInfo = await self.application_info()

        permissions = discord.Permissions(92224)
        link = discord.utils.oauth_url(
            self.appInfo.id,
            permissions=permissions
        )
        em = discord.Embed(
            title="☆★☆★GSM Bot 초대 링크★☆★☆",
            description="받으세요!",
            url=link,
            colour=self.color
        )
        msg = await message.channel.send(embed=em)
        await asyncio.sleep(15)

        try:
            await msg.delete()
            await message.channel.send("초대 링크는 자동으로 삭제했습니다.")
        except discord.errors.Forbidden:
            pass

    @public_only
    async def command_history(self, message):
        """
        해당 서버에서 채팅으로 많이 입력된 키워드들을 보여드립니다.
        """
        await message.channel.trigger_typing()

        title = "%s의 입력된 키워드 순위" % message.guild.name
        em = discord.Embed(title=title, colour=self.color)

        KEYWORD = os.path.join("..", "keyword", "%s.json" % message.guild.id)
        with open(KEYWORD, "r", encoding="UTF8") as f:
            read = json.load(f)

        sortedDict = sorted(sorted(read.items(), key=operator.itemgetter(
            0)), key=operator.itemgetter(1), reverse=True)
        # 딕셔너리를 정렬한다. 기준은 value값(입력된 횟수)의 내림차순

        for i in range(10 if len(sortedDict) > 10 else len(sortedDict)):
            em.add_field(
                name="%d위" % (i + 1),
                value="%s : %d회\n" % (sortedDict[i][0], sortedDict[i][1])
            )

        await message.channel.send(embed=em)

    @public_only
    async def command_vote(self, message):
        """
        주제를 정하고 OX 찬반 투표를 생성합니다.
        """
        if not message.channel.permissions_for(message.guild.get_member(self.user.id)).manage_messages:
            await message.channel.send(Strings.DONT_HAVE_PERMISSION)
            return

        channel_id = message.guild.id
        directory = os.path.join("..", "vote", "%s.json" % channel_id)

        if os.path.exists(directory):  # 파일이 있다면 이미 투표가 진행되고 있다는 의미
            try:
                with open(directory, "r", encoding="UTF8") as f:
                    data = json.load(f)
            except FileNotFoundError:
                await message.channel.send("%s 투표가 종료돼서 제대로 반영이 되지 않았습니다." % message.author.mention)
                return

            title = "현재 %s에 대한 투표가 진행중입니다." % data["subject"]
            desc = "%s, 1:1 채팅을 보냈습니다. 투표는 1:1 채팅에서 진행해주세요." % message.author.mention
            em = discord.Embed(
                title=title,
                description=desc,
                colour=self.color
            )
            em.add_field(
                name="투표 종료까지",
                value="%s분 남았습니다." % int((data["start"] + data["time"] - time.time()) / 60)
            )
            await message.channel.send(embed=em)

            em = discord.Embed(
                title="%s의 투표를 진행해주세요." % data["subject"], description="앞에 GSM은 붙이지 않습니다.",
                colour=self.color
            )
            em.add_field(name="찬성 투표", value="O 입력")
            em.add_field(name="반대 투표", value="X 입력")
            quest = await message.author.send(embed=em)

            response = await self.wait_for("message", check=lambda m: message.author == m.author and message.author.dm_channel == m.channel, timeout=float(30))
            # 명령어를 입력한 사용자로부터 답변을 기다린 후, response에 저장해둠

            if response is None:  # 질문에 대해 시간 초과가 일어나면 None이 리턴된다
                await quest.channel.send("%s 투표가 제대로 되지 않았습니다. 다시 시도해주세요." % message.author.mention)
                return

            content = response.content

            if content.upper() == "O" or content.upper() == "X":  # O나 X로 들어온 답변만 json파일에 입력함
                # 파일을 읽고 받아온 딕셔너리를 업데이트한다
                data[response.author.id] = content.upper()

                if os.path.exists(directory):  # 투표를 하려고 명령어를 친 후에 투표가 끝나는 경우를 위해서 파일 재검사
                    with open(directory, "w", encoding="UTF8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                else:  # 파일이 없다면 투표가 끝났다는 의미이므로 함수 종료
                    await quest.channel.send("%s 투표가 종료돼서 제대로 반영이 되지 않았습니다." % message.author.mention)
                    return

                await quest.channel.send("%s의 투표가 잘 처리되었습니다." % response.author.name)
            else:
                await quest.channel.send("%s 투표가 제대로 처리되지 않았습니다." % response.author.mention)

        else:  # 투표가 진행되고 있지 않을 때
            msg = '투표 주제와 투표 시간을 입력해주세요.\n"10분동안 설문" 이라는 제목으로 10분동안 투표하려면\nex) "10분동안 설문 10" 라고 입력해주세요. 앞에 GSM 은 붙이지 않습니다.'
            quest = await message.channel.send(msg)

            response = await self.wait_for("message", check=lambda m: message.author == m.author and message.channel == m.channel, timeout=float(30))
            await quest.delete()

            if response is None:
                await message.channel.send("%s 투표가 제대로 시작되지 않았습니다." % message.author.mention)
                return

            content = response.content
            await response.delete()

            # Cancel을 입력했다면 함수를 종료하며 투표 생성 취소
            if content.split()[0].lower() == "cancel":
                await message.channel.send("투표가 취소되었습니다.")

            try:
                # 몇 분동안 투표를 진행할건지 파악하기 위해서 스플릿 마지막 결과 저장
                _time = float(content.split()[-1])
            except ValueError:  # 문자열을 숫자로 바꾸려고 하면 ValueError 발생
                await message.channel.send("투표 시간이 제대로 입력되지 않았습니다.")
                return

            # 스플릿 마지막 결과(시간)을 제외한 나머지를 content에 저장
            content = content.split()[0:-1]
            subject = "".join([(i + " ") for i in content]
                              )  # 입력받았을 때 처럼 띄어쓰기를 넣기 위함

            # 딕셔너리에 subject와 시작 시간, 투표 기간을 저장함
            temp = {"subject": subject, "start": time.time(),
                    "time": _time * 60}
            with open(directory, "w", encoding="UTF8") as f:
                # temp 딕셔너리를 넣은 json파일 생성
                json.dump(temp, f, ensure_ascii=False, indent=4)

            em = discord.Embed(title="☆★%s의 투표★☆" %
                               message.guild.name, colour=self.color)
            em.add_field(name="%s" %
                         subject, value="gsm vote를 입력하시고 투표에 참가해주세요!")

            await message.channel.send(embed=em)
            # time을 분 단위로 받았지만 asyncio.sleep은 초 단위로 작동하므로 60을 곱해줌
            await asyncio.sleep(_time * 60)

            with open(directory, "r", encoding="UTF8") as f:
                # asyncio.sleep을 통해 대기하는 동안 추가된 데이터를 다시 읽어들임
                data = json.load(f)

            del(data["subject"], data["start"],
                data["time"])  # 투표 주제와 시간 정보를 제외한
            result = {"O": 0, "X": 0}  # 나머지 키:값쌍의 value값(O, X)을 저장함
            for i in data:
                result[data[i]] += 1  # result 딕셔너리에 저장함

            em = discord.Embed(title="☆★%s의 투표결과★☆" %
                               subject, colour=self.color)
            em.add_field(name="찬성", value=result["O"])
            em.add_field(name="반대", value=result["X"])

            await message.channel.send(embed=em)

            try:
                os.remove(directory)  # 투표가 끝났으므로 파일 삭제
            except PermissionError:  # 파일을 프로그램이 점유하고 있을 때 PermissionError 발생
                for i in range(10):  # 대략 10초동안 1초마다 삭제를 시도
                    await asyncio.sleep(1)
                    os.remove(directory)

    async def command_image(self, message):
        """
        구글에서 해당 키워드를 검색한 후, 결과를 사진으로 보내줍니다.
        """
        quest = await message.channel.send("검색어를 입력해주세요. 앞에 GSM은 붙이지 않습니다.\n취소하시려면 Cancel을 입력해주세요.")
        response = await self.wait_for("message", check=lambda m: message.author == m.author and message.channel == m.channel, timeout=float(30))

        try:
            await quest.delete()
        except discord.errors.Forbidden:
            pass

        if response is None or response.content.lower() == "cancel":
            await message.channel.send("이미지 검색이 취소되었습니다.")
            return

        await message.channel.trigger_typing()

        keyword = response.content
        try:
            await response.delete()
        except discord.errors.Forbidden:
            pass

        print("%s : image %s" % (message.author, keyword))
        image = DataManager.get_command("image", keyword)

        if image is None:
            em = discord.Embed(title="%s의 이미지 검색 결과" % keyword,
                               description="이미지를 불러올 수 없습니다.", colour=self.color)
        else:
            em = discord.Embed(title="%s의 이미지 검색 결과" %
                               keyword, colour=self.color)
            em.set_image(url=image)

        avatar = message.author.default_avatar_url if message.author.avatar_url == "" else message.author.avatar_url
        # 프로필 사진을 따로 지정해두지 않은 경우에 비어있는 문자열이 반환되므로 이 때는 기본 프로필 사진을 넣어줌
        em.set_footer(
            text="%s님이 요청하신 검색 결과" % message.author.name,
            icon_url=avatar
        )
        await message.channel.send(embed=em)

    @public_only
    async def command_peek(self, message):
        """
        GSM Bot의 종료 전까지 선택한 사용자의 상태를 계속해서 감시합니다!
        같은 사용자를 다시 입력할 시엔 감시가 해제됩니다.
        """
        quest = await message.channel.send("감시할 사용자를 언급해주세요. 앞에 GSM은 붙이지 않습니다.\n취소하시려면 Cancel을 입력해주세요.")
        response = await self.wait_for("message", check=lambda m: message.author == m.author and message.channel == m.channel, timeout=float(15))

        try:
            await quest.delete()
        except discord.errors.Forbidden:
            pass

        if response is None or response.content.lower() == "cancel":
            await message.channel.send("감시가 취소되었습니다.")
            return

        user = response.content
        # <@Discord_ID> 나 <@!Discord_ID>에서 Discord_ID만 빼오기 위해 value라는 이름으로 그룹을 지정함
        result = re.compile("<@!?(?P<value>\\d+)>").match(user)

        if result:  # 조건에 만족한다면
            # value로 이름붙인 그룹을 가져와서 discord.Member 객체를 얻음
            user = message.guild.get_member(int(result.group("value")))
        else:
            await message.channel.send("올바르지 않은 ID 값이 들어왔습니다.")
            return

        self.serverCount[user] = 0

        if not user in self.peekList.keys():  # 감시 리스트에 user가 없다면
            self.peekList[user] = [message.channel]  # 새로 추가
            await message.channel.send("%s의 감시를 시작합니다!" % user.name)
            print(get_peeklist_to_string(self.peekList))
            return
        else:  # 감시 리스트에 user가 있다면
            for i in self.peekList[user]:  # self.peekList[user]은 user의 채널의 리스트
                if i.guild == message.guild:  # 감시하고 있는 서버에서 다시 한번 입력됐을 때
                    if len(self.peekList[user]) == 1:
                        del self.peekList[user]
                    else:
                        self.peekList[user].remove(message.channel)
                    await message.channel.send("%s의 감시를 취소합니다." % user.name)
                    print(get_peeklist_to_string(self.peekList))
                    return

            # 이미 user가 있지만 새로운 서버에서 peek을 실행했을 때
            self.peekList[user].append(message.channel)
            await message.channel.send("%s의 감시를 시작합니다!" % user.name)
            print(get_peeklist_to_string(self.peekList))
            return

    @public_only
    async def command_purge(self, message):
        """
        GSM Bot이 보낸 메시지를 정리하는 기능입니다.
        최근의 20개의 메시지에서 GSM Bot의 메시지를 검색하여 삭제합니다.
        """
        if not message.channel.permissions_for(message.guild.get_member(self.user.id)).read_message_history:
            await message.channel.send("Bot에게 메시지 기록 보기 권한이 없습니다.")
            return

        num = len(await message.channel.purge(limit=20, check=lambda message: message.author == self.user))
        await message.channel.send("GSM Bot의 메시지를 %d개 삭제했습니다." % num)

    async def command_youtube(self, message):
        """
        유튜브에서 해당 키워드를 검색한 후, 원하는 결과를 URL로 보내드립니다.
        """
        options = {
            "format": "bestaudio/best",
            "extractaudio": True,
            "audioformat": "mp3",
            "outtmpl": "%(title)s.%(ext)s",
            "noplaylist": True,
            "nocheckcertificate": True,
            "ignoreerrors": True,
            "logtostderr": False,
            "quiet": True,
            "no_warnings": True
        }

        quest = await message.channel.send("유튜브 검색을 원하는 키워드를 입력해주세요. 앞에 GSM은 붙이지 않습니다.\n취소하시려면 Cancel을 입력해주세요.")
        response = await self.wait_for("message", check=lambda m: m.author == message.author and m.channel == message.channel, timeout=float(20))

        try:
            await quest.delete()
        except discord.errors.Forbidden:
            pass

        if response is None or response.content.lower() == "cancel":
            await message.channel.send("검색이 취소되었습니다.")
            return

        search_query = "ytsearch5:%s" % response.content

        status = await message.channel.send("현재 겁나 열심히 검색중입니다! (•⌄•๑)و")
        await message.channel.trigger_typing()

        with youtube_dl.YoutubeDL(options) as yt:
            info = await self.loop.run_in_executor(None, partial(yt.extract_info, search_query, download=False))

        await status.delete()

        for e in info["entries"]:
            msg = "%s개 중에서 %s번째 검색 결과입니다.\n%s\n찾는게 맞다면 :thumbsup:, 아니면 :thumbsdown:을 눌러주세요." % (
                len(info["entries"]), info["entries"].index(e) + 1, e["webpage_url"])
            query = await message.channel.send(msg)
            try:
                await query.add_reaction(u"\U0001F44D")
                await query.add_reaction(u"\U0001F44E")
            except discord.errors.Forbidden:
                pass

            try:
                response = await self.wait_for(
                    "reaction_add",
                    check=lambda re, user: re.emoji in [u"\U0001F44D", u"\U0001F44E"] and
                        user == message.author and re.message == query,
                    timeout=float(20)
                )

                if response[0].emoji == u"\U0001F44D":
                    break
            except asyncio.TimeoutError:
                break

            try:
                await query.delete()
            except discord.errors.Forbidden:
                pass

        await message.channel.send("검색을 종료합니다.")

    async def command_source(self, message):
        """
        GSM Bot의 Github 링크를 보내드립니다.
        """
        em = discord.Embed(
            title="GSM Bot Source Code",
            description="받으세요!",
            url=Strings.GITHUB,
            colour=self.color
        )
        msg = await message.channel.send(embed=em)
        await asyncio.sleep(15)

        try:
            await msg.delete()
            await message.channel.send("Github 링크는 자동으로 삭제했습니다.")
        except discord.errors.Forbidden:
            pass

    async def message_log(self, message):
        # 해당 서버의 고유 아이디마다 json파일을 생성
        directory = os.path.join("..", "keyword", "%s.json" % message.guild.id)

        if os.path.exists(directory):  # 파일이 이미 존재한다면
            with open(directory, "r", encoding="UTF8") as f:
                temp = json.load(f)  # 파일을 딕셔너리로 읽어온다
        else:  # 파일이 없다면
            temp = {}  # 비어있는 딕셔너리 생성

        for i in message.content.split():
            if i in self.commands:  # 명령어는 키워드로 카운트하지 않기 위해서 제외함
                continue
            # 키워드가 이미 있는지 없는지 검사해서, 있다면 기존 값 + 1 리턴, 없다면 1 리턴
            value = (lambda _bool: temp[i] +
                     1 if _bool else 1)(i in temp.keys())
            # temp 딕셔너리를 업데이트한다. 값이 이미 있다면 값을 바꾸고, 없다면 새로 키:값 쌍을 추가한다
            temp[i] = value

        with open(directory, "w", encoding="UTF8") as f:  # 파일을 쓰기 모드로 열어서
            json.dump(temp, f, ensure_ascii=False, indent=4)  # 새로운 값으로 덮어쓰기한다
