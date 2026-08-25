import discord
from discord.ext import commands
from discord import app_commands

class Distribute(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="분배", description="보스 수익금을 파티원 수에 맞게 분배합니다.")
    @app_commands.describe(
        amount="분배할 총 금액 (숫자만 입력)", 
        people="파티 인원 수", 
        percents="(선택) 차등 분배 시 퍼센트를 띄어쓰기나 쉼표로 입력 (예: 30 30 40)"
    )
    async def split_meso(self, interaction: discord.Interaction, amount: int, people: int, percents: str = None):
        if not percents:
            # 1. 퍼센트 옵션이 없을 때 (기본 1/N 균등 분배)
            per_person = amount // people
            await interaction.response.send_message(f"💰 총 **{amount:,}** 메소를 {people}명에게 균등 분배합니다.\n👉 **1인당 {per_person:,} 메소**")
            
        else:
            # 2. 퍼센트 옵션이 있을 때 (차등 분배)
            try:
                # 쉼표를 공백으로 바꾸고 분리 (30,30,40 이나 30 30 40 모두 지원)
                cleaned_str = percents.replace(",", " ")
                percent_list = [float(p.strip()) for p in cleaned_str.split() if p.strip()]
                
                # 입력된 퍼센트 개수와 인원수가 맞는지 확인
                if len(percent_list) != people:
                    return await interaction.response.send_message(
                        f"⚠️ 인원수({people}명)와 입력한 퍼센트의 개수({len(percent_list)}개)가 일치하지 않습니다!", 
                        ephemeral=True
                    )
                
                # 합이 100%인지 확인 (33.3 33.3 33.4 같은 경우를 위해 부동소수점 오차 아주 살짝 허용)
                total_percent = sum(percent_list)
                if not (99.9 <= total_percent <= 100.1): 
                    return await interaction.response.send_message(
                        f"⚠️ 입력한 퍼센트의 합이 100%가 아닙니다! (현재 합: {total_percent}%)\n비율을 다시 확인해주세요.", 
                        ephemeral=True
                    )
                
                result_text = f"💰 총 **{amount:,}** 메소 차등 분배 결과\n\n"
                
                # 중복되는 퍼센트끼리 묶어서 출력용 데이터 만들기
                percent_counts = {}
                for p in percent_list:
                    percent_counts[p] = percent_counts.get(p, 0) + 1
                    
                for p, count in sorted(percent_counts.items(), reverse=True):
                    # 금액 = 총금액 * (퍼센트 / 100)
                    person_cut = int(amount * (p / 100))
                    
                    # 30.0% 처럼 보이지 않게 정수는 깔끔하게 자르기
                    display_p = int(p) if p.is_integer() else p
                    result_text += f"🔹 **{display_p}% ({count}명):** 인당 **{person_cut:,}** 메소\n"
                    
                await interaction.response.send_message(result_text)
                
            except ValueError:
                await interaction.response.send_message(
                    "⚠️ 퍼센트는 숫자로만 입력해주세요. (예: 30 30 40 또는 30,30,40)", 
                    ephemeral=True
                )

async def setup(bot):
    await bot.add_cog(Distribute(bot))